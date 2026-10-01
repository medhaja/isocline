"""FastAPI application: /api/v1 (session cookies or personal access tokens) and /hooks (webhook triggers)."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from isocline import __version__
from isocline.api.deps import CSRF_COOKIE, SESSION_COOKIE
from isocline.api.routes import (
    agents, ai, artifacts, auth, evaluations, governance, harness, knowledge, monitoring, providers, quality,
    runs, triggers, usage, workflows, workspaces,
)
from isocline.core.config import get_settings
from isocline.core.logging import configure_logging, log
from isocline.core.security import constant_time_eq
from isocline.db import session as dbs
from isocline.services.ratelimit import hit

CSRF_EXEMPT = ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
               "/api/v1/auth/verify-email")


def setup_tracing(app: FastAPI) -> None:
    """OpenTelemetry traces for every request. Exported via OTLP when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
    import os
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider(resource=Resource.create({"service.name": "isocline-api"}))
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    except Exception as e:  # tracing must never prevent the API from starting
        log.warning("tracing_disabled", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    s = get_settings()
    if s.env == "production" and (s.secret_key.startswith("dev-only") or not s.encryption_key):
        raise RuntimeError("Set ISOCLINE_SECRET_KEY and ISOCLINE_ENCRYPTION_KEY in production")
    if s.env == "production" and s.enable_test_provider:
        log.warning("test_provider_enabled_in_production")
    if s.env != "test":
        from isocline.db.seed import bootstrap_admin, seed
        try:
            async with dbs.sessionmaker()() as db:
                await seed(db)
                await bootstrap_admin(db)
        except Exception as e:
            log.error("seed_failed", error=str(e))
    loop_task = None
    if s.inline_worker and s.env != "test":
        import asyncio

        async def dev_scheduler():
            """DEV ONLY (inline worker): what Celery beat does in production."""
            from isocline.services.triggers import fire_due_schedules
            from isocline.services.waits import process_due_waits
            tick = 0
            while True:
                try:
                    async with dbs.sessionmaker()() as db:
                        await process_due_waits(db)
                        if tick % 4 == 0:
                            await fire_due_schedules(db)
                except Exception as e:
                    log.warning("dev_scheduler_error", error=str(e))
                tick += 1
                await asyncio.sleep(5)
        loop_task = asyncio.create_task(dev_scheduler())
    yield
    if loop_task:
        loop_task.cancel()
    await dbs.engine().dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Isocline API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        request.state.request_id = rid
        path = request.url.path
        client = request.client.host if request.client else "unknown"
        # --- rate limiting (per IP for auth endpoints, per session/IP otherwise)
        if path.startswith("/api/v1/auth/") and request.method == "POST":
            if not await hit(f"auth:{client}", s.auth_rate_limit_per_minute):
                return _err(429, "rate_limited", "Too many attempts. Try again in a minute.", rid)
        elif path.startswith("/api/v1/") and not path.endswith("/events"):
            ident = request.cookies.get(SESSION_COOKIE, "")[-24:] or client
            # Separate budgets: background reads (polling live pages) must never use up the write allowance.
            kind = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "write"
            if not await hit(f"api-{kind}:{ident}", s.rate_limit_per_minute * (5 if kind == "read" else 1)):
                return _err(429, "rate_limited", "Too many requests. Slow down and retry shortly.", rid)
        # --- CSRF: double-submit cookie for cookie-authenticated state-changing requests
        bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        if (path.startswith("/api/v1/") and request.method in ("POST", "PUT", "PATCH", "DELETE")
                and path not in CSRF_EXEMPT and request.cookies.get(SESSION_COOKIE) and not bearer):
            cookie, header = request.cookies.get(CSRF_COOKIE, ""), request.headers.get("x-csrf-token", "")
            if not cookie or not header or not constant_time_eq(cookie, header):
                return _err(403, "csrf_failed", "Missing or invalid CSRF token. Reload the page and try again.", rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled_error", path=path, method=request.method)
            return _err(500, "internal_error", "Something went wrong. Reference: " + rid, rid)
        ms = int((time.perf_counter() - t0) * 1000)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not path.endswith("/events"):
            log.info("request", method=request.method, path=path, status=response.status_code, duration_ms=ms,
                     user_id=getattr(request.state, "user_id", None))
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"error": {**d, "request_id": getattr(request.state, "request_id", None)}}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()[:20]]
        return JSONResponse({"error": {"code": "invalid_request", "message": details[0]["message"] if details else "Invalid request",
                                       "details": details, "request_id": getattr(request.state, "request_id", None)}}, status_code=422)

    api = "/api/v1"
    for r in (auth, workspaces, workflows, runs, agents, providers, knowledge, evaluations, usage, ai,
              harness, governance, artifacts, triggers, quality, monitoring):
        app.include_router(r.router, prefix=api)
    app.include_router(triggers.public)  # /hooks/{id}
    app.include_router(triggers.public, prefix="/v1", include_in_schema=False)  # /v1/hooks, /v1/callbacks

    @app.get(f"{api}/meta", tags=["meta"])
    async def meta():
        """Installation facts the web UI needs before sign-in."""
        return {"name": "Isocline", "version": __version__, "edition": "oss",
                "test_provider": s.enable_test_provider, "signup": "open" if s.allow_signup else "first_account_only"}

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        async with dbs.sessionmaker()() as db:
            await db.execute(text("select 1"))
        return {"ok": True}

    setup_tracing(app)
    return app


def _err(status: int, code: str, message: str, rid: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "request_id": rid}}, status_code=status)


app = create_app()
