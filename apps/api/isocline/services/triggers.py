"""Triggers: webhook, schedule, event and file upload. Triggered runs always execute the latest published version.

Webhooks: POST /hooks/{public_id}
  * auth "hmac" (default): X-Isocline-Timestamp + X-Isocline-Signature: sha256=<hex HMAC(secret, "{ts}.{body}")>,
    5-minute window; the signature is single-use (replay protection)
  * auth "token": X-Isocline-Token must equal the secret
  * Idempotency-Key header → the same delivery returns the same run
  * optional JSON payload schema; per-trigger rate limit
Schedules: 5-field cron (min hour dom month dow) with an IANA timezone. Fired from the database with an idempotency
key per scheduled slot, so a restart or two beat instances never fire a slot twice."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError
from isocline.core.logging import log
from isocline.core.security import decrypt_secret
from isocline.db.models import Project, Workflow, WorkflowVersion, utcnow
from isocline.db.models_v2 import Trigger, TriggerDelivery

PRESETS = {"hourly": "0 * * * *", "daily": "0 9 * * *", "weekly": "0 9 * * 1", "monthly": "0 9 1 * *"}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DOWS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}
SIGNATURE_WINDOW = 300


# ------------------------------------------------------------------------------------------ cron
def _field(expr: str, lo: int, hi: int, names: dict | None = None) -> set[int]:
    out: set[int] = set()
    for part in expr.lower().split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step < 1:
                raise ValueError("step must be positive")
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = _val(x, names), _val(y, names)
        else:
            a = b = _val(part, names)
            if step > 1:
                b = hi
        if a < lo or b > hi or a > b:
            raise ValueError(f"value out of range {lo}-{hi}")
        out |= set(range(a, b + 1, step))
    return out


def _val(x: str, names: dict | None) -> int:
    if names and x in names:
        return names[x]
    return int(x)


def parse_cron(cron: str) -> dict:
    cron = PRESETS.get(cron.strip(), cron.strip())
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError("Use 5 fields: minute hour day-of-month month day-of-week (or hourly/daily/weekly/monthly)")
    dow = _field(parts[4], 0, 7, _DOWS)
    if 7 in dow:
        dow = (dow - {7}) | {0}
    return {"min": _field(parts[0], 0, 59), "hour": _field(parts[1], 0, 23), "dom": _field(parts[2], 1, 31),
            "month": _field(parts[3], 1, 12, _MONTHS), "dow": dow, "dom_any": parts[2] == "*", "dow_any": parts[4] == "*"}


def next_fire(cron: str, after: datetime, tz: str = "UTC") -> datetime:
    """Next firing time strictly after `after` (UTC-aware result)."""
    spec = parse_cron(cron)
    zone = ZoneInfo(tz or "UTC")
    start = (after.astimezone(zone) + timedelta(minutes=1)).replace(second=0, microsecond=0)
    for offset in range(0, 366 * 5):
        d: date = start.date() + timedelta(days=offset)
        if d.month not in spec["month"]:
            continue
        dom_ok, dow_ok = d.day in spec["dom"], (d.isoweekday() % 7) in spec["dow"]
        if spec["dom_any"] and spec["dow_any"]:
            day_ok = True
        elif spec["dom_any"]:
            day_ok = dow_ok
        elif spec["dow_any"]:
            day_ok = dom_ok
        else:
            day_ok = dom_ok or dow_ok  # standard cron semantics when both are restricted
        if not day_ok:
            continue
        for h in sorted(spec["hour"]):
            for m in sorted(spec["min"]):
                cand = datetime(d.year, d.month, d.day, h, m, tzinfo=zone)
                if cand >= start:
                    return cand.astimezone(timezone.utc)
    raise ValueError("Schedule never fires")


# ------------------------------------------------------------------------------------------ run creation
async def _target_version(db: AsyncSession, t: Trigger) -> WorkflowVersion:
    v = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == t.workflow_id)
                          .order_by(WorkflowVersion.version.desc()).limit(1))).scalar_one_or_none()
    if v is None:
        raise AppError(409, "not_published", "Publish the workflow before it can be triggered")
    return v


def map_input(t: Trigger, payload: Any) -> Any:
    mapping = (t.config or {}).get("input_mapping") or {}
    if not mapping:
        return payload if isinstance(payload, dict) else {"payload": payload}
    from isocline.engine.expressions import Scope, resolve_value
    sc = Scope(payload if isinstance(payload, dict) else {"payload": payload}, {})
    return {k: resolve_value(v, sc) for k, v in mapping.items()}


async def start_triggered_run(db: AsyncSession, t: Trigger, payload: Any, idempotency_key: str, kind: str):
    from isocline.services.runs import create_run
    wf = await db.get(Workflow, t.workflow_id)
    project = await db.get(Project, t.project_id)
    version = await _target_version(db, t)
    schema = (t.config or {}).get("payload_schema")
    if schema:
        from isocline.engine.structured import normalize_schema, validate
        errs = validate(payload, normalize_schema(schema))
        if errs:
            raise AppError(422, "invalid_payload", "Payload does not match the trigger's schema", errs[:10])
    return await create_run(db, workflow=wf, project=project, run_input=map_input(t, payload), trigger=kind, version=version,
                            idempotency_key=idempotency_key[:200], trigger_id=t.id)


# ------------------------------------------------------------------------------------------ webhooks
def sign(secret: str, ts: int, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def verify_webhook(t: Trigger, headers: dict, body: bytes) -> str:
    """Returns the dedupe key for this delivery or raises AppError(401)."""
    secret = decrypt_secret(t.secret_encrypted) if t.secret_encrypted else ""
    mode = (t.config or {}).get("auth", "hmac")
    if mode == "token":
        tok = headers.get("x-isocline-token", "")
        if not secret or not hmac.compare_digest(tok, secret):
            raise AppError(401, "invalid_token", "Missing or invalid X-Isocline-Token")
        return headers.get("idempotency-key") or hashlib.sha256(body).hexdigest() + f":{int(time.time() // 60)}"
    ts_raw, sig = headers.get("x-isocline-timestamp", ""), headers.get("x-isocline-signature", "")
    if not ts_raw.isdigit() or not sig:
        raise AppError(401, "missing_signature", "Sign requests with X-Isocline-Timestamp and X-Isocline-Signature")
    ts = int(ts_raw)
    if abs(time.time() - ts) > SIGNATURE_WINDOW:
        raise AppError(401, "stale_signature", "Timestamp outside the 5-minute window")
    if not hmac.compare_digest(sign(secret, ts, body), sig):
        raise AppError(401, "invalid_signature", "Signature does not match")
    return headers.get("idempotency-key") or f"sig:{sig}"


async def deliver_webhook(db: AsyncSession, t: Trigger, headers: dict, body: bytes) -> dict:
    from isocline.services.ratelimit import hit
    if not t.enabled:
        raise AppError(409, "trigger_disabled", "This trigger is disabled")
    key = verify_webhook(t, headers, body)
    if not await hit(f"hook:{t.id}", int((t.config or {}).get("rate_limit_per_minute") or 60)):
        raise AppError(429, "rate_limited", "Too many deliveries for this webhook")
    existing = (await db.execute(select(TriggerDelivery).where(TriggerDelivery.trigger_id == t.id, TriggerDelivery.dedupe_key == key))).scalar_one_or_none()
    if existing:
        if key.startswith("sig:"):
            raise AppError(409, "replayed", "This signed delivery was already received")
        return {"run_id": str(existing.run_id) if existing.run_id else None, "duplicate": True}
    try:
        payload = json.loads(body or b"{}")
    except ValueError as e:
        raise AppError(400, "invalid_json", "Body must be JSON") from e
    d = TriggerDelivery(trigger_id=t.id, dedupe_key=key)
    db.add(d)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise AppError(409, "replayed", "This delivery was already received") from e
    run = await start_triggered_run(db, t, payload, f"hook:{t.id}:{key}", "webhook")
    d.run_id = run.id
    t.last_run_at = utcnow()
    await db.commit()
    return {"run_id": str(run.id), "status": run.status}


# ------------------------------------------------------------------------------------------ schedules & events
async def fire_due_schedules(db: AsyncSession) -> int:
    now = utcnow()
    due = (await db.execute(select(Trigger).where(Trigger.kind == "schedule", Trigger.enabled == True,  # noqa: E712
                                                  Trigger.next_run_at <= now).limit(200))).scalars().all()
    fired = 0
    for t in due:
        slot = t.next_run_at if t.next_run_at.tzinfo else t.next_run_at.replace(tzinfo=timezone.utc)
        cfg = t.config or {}
        try:
            await start_triggered_run(db, t, {"scheduled_for": slot.isoformat(), **(cfg.get("payload") or {})},
                                      f"sched:{t.id}:{slot.isoformat()}", "schedule")
            fired += 1
        except Exception as e:  # a failing schedule must not block the others
            await db.rollback()
            t = await db.get(Trigger, t.id)
            log.warning("schedule_failed", trigger_id=str(t.id), error=str(e))
            t.config = {**(t.config or {}), "last_error": str(getattr(e, "detail", e))[:500]}
        t.last_run_at = now
        t.next_run_at = next_fire(cfg.get("cron", "daily"), max(now, slot), cfg.get("timezone", "UTC"))
        await db.commit()
    return fired


async def fire_event_triggers(db: AsyncSession, workspace_id, name: str, correlation_key: str | None, payload: Any) -> list[str]:
    rows = (await db.execute(select(Trigger).join(Project, Project.id == Trigger.project_id)
                             .where(Project.workspace_id == workspace_id, Trigger.kind == "event", Trigger.enabled == True))).scalars().all()  # noqa: E712
    runs = []
    for t in rows:
        if (t.config or {}).get("event_name") != name:
            continue
        key = f"event:{t.id}:{correlation_key or hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()}"
        try:
            r = await start_triggered_run(db, t, {"event": name, "correlation_key": correlation_key, "payload": payload}, key, "event")
            runs.append(str(r.id))
        except AppError as e:
            log.warning("event_trigger_failed", trigger_id=str(t.id), error=str(e.detail))
    return runs


async def fire_file_triggers(db: AsyncSession, document) -> list[str]:
    rows = (await db.execute(select(Trigger).where(Trigger.project_id == document.project_id, Trigger.kind == "file",
                                                   Trigger.enabled == True))).scalars().all()  # noqa: E712
    runs = []
    for t in rows:
        cfg = t.config or {}
        exts = [e.lower() for e in cfg.get("extensions") or []]
        if exts and not any(document.filename.lower().endswith(e) for e in exts):
            continue
        if cfg.get("knowledge_base_id") and str(document.knowledge_base_id) != cfg["knowledge_base_id"]:
            continue
        try:
            r = await start_triggered_run(db, t, {"file": str(document.id), "filename": document.filename, "mime": document.mime},
                                          f"file:{t.id}:{document.id}", "file")
            runs.append(str(r.id))
        except AppError as e:
            log.warning("file_trigger_failed", trigger_id=str(t.id), error=str(e.detail))
    return runs
