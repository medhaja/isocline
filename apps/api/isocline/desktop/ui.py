"""Serves the statically exported Next.js UI (apps/web with output: "export") from the API, so the browser talks to one
origin and no Node.js runtime ships with the desktop app.

Resolution for GET /some/path: the file itself, some/path.html, some/path/index.html, then 404.html."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

RESERVED = ("api/", "v1/", "hooks/", "healthz", "readyz")
# Record pages moved from /runs/<id> to /runs/view?id=<id>; old links and bookmarks keep working (same rule as the
# redirects in apps/web/next.config.mjs for the server build).
LEGACY = re.compile(r"^(runs|workflows|projects|evaluations)/(?!view$|compare$)([^/]+)/?$")


def mount(app: FastAPI, root: str) -> None:
    base = Path(root).resolve()

    def resolve(rel: str) -> Path | None:
        rel = rel.strip("/")
        for candidate in (rel, f"{rel}.html", f"{rel}/index.html" if rel else "index.html"):
            p = (base / candidate).resolve()
            if p.is_file() and p.is_relative_to(base):  # never serve outside the UI directory
                return p
        return None

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def ui(request: Request, path: str = ""):
        if path.startswith(RESERVED):
            raise HTTPException(404, {"code": "not_found", "message": "Not found"})
        legacy = LEGACY.match(path)
        if legacy and not legacy[2].endswith((".html", ".txt")):
            extra = f"&{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"/{legacy[1]}/view?id={quote(legacy[2])}{extra}", status_code=307)
        p = resolve(path)
        if p is not None:
            # Hashed build assets never change; pages must be revalidated so an app update takes effect.
            immutable = "/_next/static/" in p.as_posix()
            return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        missing = base / "404.html"
        if missing.is_file():
            return FileResponse(missing, status_code=404, headers={"Cache-Control": "no-cache"})
        raise HTTPException(404, {"code": "not_found", "message": "Not found"})
