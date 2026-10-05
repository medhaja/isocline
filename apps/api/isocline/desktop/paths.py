"""Where the desktop app keeps its data, and where bundled resources live (source tree or PyInstaller bundle)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Isocline"


def data_dir(override: str | None = None) -> Path:
    """Per-user, writable data directory.

    Windows: %LOCALAPPDATA%\\Isocline   macOS: ~/Library/Application Support/Isocline   Linux: $XDG_DATA_HOME/isocline

    Running from source (`python -m isocline.desktop`) uses a separate "Isocline-dev" folder, so a developer's test
    accounts, keys and projects never show up in the installed app, and vice versa."""
    if override:
        p = Path(override).expanduser()
    elif os.environ.get("ISOCLINE_DATA_DIR"):
        p = Path(os.environ["ISOCLINE_DATA_DIR"]).expanduser()
    else:
        name = APP_NAME if frozen() else f"{APP_NAME}-dev"
        if sys.platform == "win32":
            p = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / name
        elif sys.platform == "darwin":
            p = Path.home() / "Library" / "Application Support" / name
        else:
            p = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / name.lower()
    p.mkdir(parents=True, exist_ok=True)
    return p


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Root that contains ``alembic/``, ``alembic.ini`` and ``web/`` (the exported UI).

    In a PyInstaller build these are bundled next to the code (sys._MEIPASS). From source, ``apps/api`` holds the
    migrations and the exported UI is looked up in ``apps/web/out``."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]  # apps/api


def migrations_dir() -> Path:
    return resource_root() / "alembic"


def ui_dir() -> Path | None:
    candidates = [resource_root() / "web"]
    if not frozen():
        candidates.append(resource_root().parent / "web" / "out")  # apps/web/out after `next build` with export
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None
