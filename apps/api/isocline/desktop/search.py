"""Starts and stops the local web search service (IsoclineSearch: a small front end to SearXNG).

SearXNG is AGPL-licensed, so it runs as a separate program and Isocline talks to it over HTTP on 127.0.0.1, as the
server edition talks to its SearXNG container. Isocline never imports it. If the search program is not available
(e.g. running from source without SearXNG installed), the app works normally and the Web Search tool reports that
local search is unavailable; a Tavily or Brave key still works.
"""
from __future__ import annotations

import importlib.util
import secrets
import subprocess
import sys
from pathlib import Path

from isocline.desktop import paths

SETTINGS_TEMPLATE = "settings.template.yml"


def _source_dir() -> Path:
    """apps/desktop-search in the source tree; the bundle root (sys._MEIPASS) in the packaged app."""
    return paths.resource_root() if paths.frozen() else paths.resource_root().parent / "desktop-search"


def command(port: int, settings: Path) -> list[str] | None:
    args = ["--port", str(port), "--settings", str(settings)]
    if paths.frozen():
        exe = Path(sys.executable).with_name("IsoclineSearch.exe" if sys.platform == "win32" else "IsoclineSearch")
        return [str(exe), *args] if exe.is_file() else None
    script = _source_dir() / "isocline_search.py"
    if script.is_file() and importlib.util.find_spec("searx") is not None:
        return [sys.executable, str(script), *args]
    return None


def ensure_settings(data: Path) -> Path:
    """<data>/searxng/settings.yml, written once from the template (users may edit it to change engines)."""
    folder = data / "searxng"
    folder.mkdir(exist_ok=True)
    path = folder / "settings.yml"
    if not path.exists():
        template = (_source_dir() / SETTINGS_TEMPLATE).read_text(encoding="utf-8")
        path.write_text(template.replace("__SECRET__", secrets.token_hex(32)), encoding="utf-8")
    return path


class SearchService:
    def __init__(self, data: Path, port: int):
        self.data, self.port = data, port
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> bool:
        try:
            settings = ensure_settings(self.data)
        except OSError as e:
            print(f"local search disabled: {e}", file=sys.stderr)
            return False
        cmd = command(self.port, settings)
        if cmd is None:
            print("local search not available in this build (SearXNG not installed)", file=sys.stderr)
            return False
        log = open(self.data / "logs" / "search.log", "a", encoding="utf-8")  # noqa: SIM115 - owned by the child
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # stdin stays open for the child's lifetime: when this process exits, the child sees EOF and exits too.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=flags, cwd=str(self.data))
        return True

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        self.proc = None
