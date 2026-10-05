"""Prepares the process environment for desktop mode. Must run before anything imports isocline.core.config,
because settings are read once from the environment (and cached)."""
from __future__ import annotations

import os
from pathlib import Path

from isocline.desktop import paths

SECRETS_FILE = "secrets.env"


def _load_env_file(path: Path) -> None:
    """Same rule as the Docker entrypoint: values already set in the environment win; split on the first '='."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.replace("_", "").isalnum() and not os.environ.get(key):
            os.environ[key] = value


def ensure_secrets(data: Path) -> Path:
    """Generates the installation's secrets on first start (signing key, vault key, sandbox token).

    Deleting this file makes stored credentials unreadable and signs the user out, exactly like the Docker
    ``secrets`` volume."""
    from isocline.core.bootstrap_secrets import generate

    path = data / SECRETS_FILE
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for k, v in generate().items():
                f.write(f"{k}={v}\n")
    return path


def prepare(port: int, data_dir: str | None = None, search_port: int | None = None) -> Path:
    """Sets ISOCLINE_* for a single-user, local-only installation. Returns the data directory."""
    data = paths.data_dir(data_dir)
    (data / "uploads").mkdir(exist_ok=True)
    (data / "logs").mkdir(exist_ok=True)

    # User overrides: <data>/isocline.env (e.g. OPENAI_API_KEY=..., OLLAMA_BASE_URL=...). Keys can also be added in the UI.
    user_env = data / "isocline.env"
    if user_env.is_file():
        _load_env_file(user_env)
    _load_env_file(ensure_secrets(data))

    origin = f"http://127.0.0.1:{port}"
    db_path = (data / "isocline.db").as_posix()
    defaults = {
        "ISOCLINE_MODE": "desktop",
        "ISOCLINE_ENV": "desktop",
        "ISOCLINE_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "ISOCLINE_STORAGE_BACKEND": "local",
        "ISOCLINE_STORAGE_LOCAL_PATH": str(data / "uploads"),
        "ISOCLINE_PUBLIC_BASE_URL": origin,
        "ISOCLINE_CORS_ORIGINS": f'["{origin}", "http://localhost:{port}"]',
        "ISOCLINE_COOKIE_SECURE": "false",
        "ISOCLINE_ALLOW_SIGNUP": "false",
        "ISOCLINE_EMBEDDING_PROVIDER": "hashing",
        "ISOCLINE_ENABLE_TEST_PROVIDER": "true",
        # Web Search: a Tavily/Brave key if one is configured, otherwise the bundled local search (SearXNG, run as a
        # separate process by the launcher; see isocline.desktop.search).
        "ISOCLINE_SEARCH_PROVIDER": "auto",
        "ISOCLINE_SEARXNG_URL": f"http://127.0.0.1:{search_port or 9}",
        # Ollama on the same machine, not the Docker host alias.
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        # Python steps run in a local AppContainer sandbox (isocline.desktop.sandbox), not the HTTP sandbox service.
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)
    ui = paths.ui_dir()
    if ui is not None:
        os.environ.setdefault("ISOCLINE_UI_DIR", str(ui))
    return data


def run_migrations() -> None:
    """Brings the SQLite schema up to date (alembic upgrade head). Runs before the server's event loop starts,
    because alembic/env.py drives its own asyncio loop."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(paths.migrations_dir()))
    command.upgrade(cfg, "head")
