# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local web search for Isocline Desktop: a minimal HTTP front end to the SearXNG metasearch library.

This is a separate program (IsoclineSearch.exe in the desktop build), licensed AGPL-3.0-or-later like SearXNG
itself. Isocline talks to it only over HTTP on 127.0.0.1, exactly as the server edition talks to the SearXNG
container; it never imports SearXNG.

    isocline_search.py --port 47322 --settings <data>/searxng/settings.yml

Endpoints (loopback only):
    GET /healthz                       -> {"ok": true}
    GET /search?q=...&format=json      -> SearXNG-compatible {"query", "results": [{title, url, content, engine}],
                                          "unresponsive_engines": [[engine, error], ...]}

The process exits when its parent closes stdin, so it never outlives the app.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time


def _exit_with_parent() -> None:
    """The launcher keeps our stdin open; EOF means it exited (or crashed). Works the same on Windows and POSIX."""
    def watch():
        try:
            while sys.stdin.buffer.read(1024):
                pass
        except Exception:
            pass
        os._exit(0)
    if sys.stdin is not None:
        threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="isocline-search")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--settings", required=True, help="SearXNG settings.yml")
    ap.add_argument("--no-parent-watch", action="store_true")
    args = ap.parse_args(argv)

    os.environ["SEARXNG_SETTINGS_PATH"] = args.settings  # must be set before searx is imported
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.no_parent_watch:
        _exit_with_parent()

    import flask
    from werkzeug.serving import make_server

    # A packaged build has no git checkout; hide SearXNG's version-probe noise, but keep real configuration errors.
    logging.getLogger("searx.version").setLevel(logging.CRITICAL)
    import searx.search
    from searx import settings
    logging.getLogger("searx").setLevel(logging.WARNING)
    from searx.search.models import EngineRef, SearchQuery

    searx.search.initialize(enable_metrics=False)
    engines = [e["name"] for e in settings["engines"] if not e.get("disabled") and "general" in (e.get("categories") or ["general"])]
    app = flask.Flask("isocline-search")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "engines": engines}

    @app.get("/search")
    def search():
        q = (flask.request.args.get("q") or "").strip()
        if not q:
            return {"error": "q is required"}, 400
        pageno = max(1, min(5, int(flask.request.args.get("pageno") or 1)))
        lang = flask.request.args.get("language") or "all"
        # SearXNG's search pipeline records timings on the current request.
        flask.request.start_time = time.time()
        flask.request.timings = []
        flask.request.errors = []
        query = SearchQuery(q, [EngineRef(name, "general") for name in engines], lang, 0, pageno)
        res = searx.search.Search(query).search()
        results = [{"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", ""),
                    "engine": r.get("engine", "")}
                   for r in (x if isinstance(x, dict) else x.as_dict() for x in res.get_ordered_results()) if r.get("url")]
        return {"query": q, "results": results,
                "unresponsive_engines": [[u.engine, u.error_type] for u in res.unresponsive_engines]}

    server = make_server("127.0.0.1", args.port, app, threaded=True)
    print(f"isocline-search listening on 127.0.0.1:{args.port} with {len(engines)} engines", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
