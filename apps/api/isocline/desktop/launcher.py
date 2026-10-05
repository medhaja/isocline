"""Isocline Desktop launcher.

Starts the API (with in-process workers and the static UI) on 127.0.0.1 and opens it in a native window
(pywebview: Edge WebView2 on Windows, WebKit on macOS). Falls back to the default browser when pywebview is missing
or --browser is given. Closing the window stops the server.

    python -m isocline.desktop [--port N] [--data-dir PATH] [--browser] [--headless] [--debug]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PREFERRED_PORT = 47321  # stable port keeps the sign-in cookie and bookmarks valid across launches
INSTANCE_FILE = "instance.json"


# --------------------------------------------------------------------------------------------------------- helpers
def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:  # same as uvicorn: a socket left in TIME_WAIT by a crashed instance must not block the restart
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _any_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pick_port(requested: int | None) -> int:
    if requested:
        return requested
    if _port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    return _any_free_port()


def _healthy(url: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/healthz", timeout=timeout) as r:  # noqa: S310 - fixed loopback URL
            return r.status == 200
    except Exception:
        return False


def _running_instance(data: Path) -> str | None:
    """URL of an Isocline already running for this data directory, if any (one process per database)."""
    f = data / INSTANCE_FILE
    try:
        url = json.loads(f.read_text(encoding="utf-8"))["url"]
    except Exception:
        return None
    return url if _healthy(url) else None


def _redirect_output(data: Path) -> None:
    """A windowed (no-console) build has no stdout/stderr; logging to None would crash. Log to a file instead."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        path = data / "logs" / "isocline.log"
        try:  # keep the log small: start a new file once it passes 5 MB (one previous file is kept)
            if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
                path.replace(path.with_suffix(".log.1"))
        except OSError:
            pass
        log_file = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stderr = log_file


def _fatal(message: str) -> int:
    print(f"Isocline could not start: {message}", file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Isocline could not start", 0x10)
        except Exception:
            pass
    return 1


# ---------------------------------------------------------------------------------------------------------- server
class Server:
    def __init__(self, port: int, debug: bool):
        import uvicorn
        config = uvicorn.Config(
            "isocline.main:app", host="127.0.0.1", port=port, loop="asyncio", http="h11", ws="none",
            lifespan="on", log_config=None, log_level="debug" if debug else "warning", access_log=debug,
            timeout_graceful_shutdown=8,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="isocline-server", daemon=True)

    def start(self, url: str, timeout: float = 90.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _healthy(url):
                return
            if not self.thread.is_alive():
                raise RuntimeError("the server stopped during startup; see logs/isocline.log")
            time.sleep(0.2)
        raise RuntimeError(f"the server did not become ready within {int(timeout)} seconds")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


# ------------------------------------------------------------------------------------------------------------- UI
def _open_window(url: str, data: Path) -> bool:
    """Blocks until the window closes. Returns False if no native window is available."""
    try:
        import webview
    except ImportError:
        return False
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # artifact and export downloads
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:
        pass
    try:
        webview.create_window("Isocline", url, width=1440, height=900, min_size=(1024, 680), text_select=True)
        # private_mode=False + storage_path: keep the sign-in cookie between launches.
        webview.start(private_mode=False, storage_path=str(data / "webview"))
    except Exception as e:  # e.g. the Edge WebView2 runtime is missing: use the browser instead of failing
        print(f"Native window unavailable ({e}); opening the default browser", file=sys.stderr)
        return False
    return True


def _wait_in_browser(url: str, server: Server) -> None:
    webbrowser.open(url)
    print(f"Isocline is running at {url}  (press Ctrl+C to stop)")
    try:
        while server.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="isocline", description="Run Isocline as a desktop app.")
    ap.add_argument("--port", type=int, help=f"port on 127.0.0.1 (default {PREFERRED_PORT}, or a free one)")
    ap.add_argument("--data-dir", help="where the database, uploads, secrets and logs live")
    ap.add_argument("--browser", action="store_true", help="open in the default browser instead of a native window")
    ap.add_argument("--headless", action="store_true", help="start the server only (no window, no browser)")
    ap.add_argument("--debug", action="store_true", help="verbose logs and request logging")
    ap.add_argument("--remove-sandbox-profile", action="store_true", help=argparse.SUPPRESS)  # used by the uninstaller
    args = ap.parse_args(argv)
    if args.remove_sandbox_profile:
        if sys.platform == "win32":
            from isocline.desktop.sandbox import appcontainer
            appcontainer.remove_profile()
        return 0

    from isocline.desktop import paths
    data = paths.data_dir(args.data_dir)
    (data / "logs").mkdir(exist_ok=True)
    _redirect_output(data)

    existing = _running_instance(data)
    if existing:  # second launch: just show the running app
        if args.headless or args.browser or not _open_window(existing, data):
            webbrowser.open(existing)
        return 0

    port = _pick_port(args.port)
    if not _port_free(port):  # otherwise the readiness check could be answered by whatever holds the port
        return _fatal(f"port {port} is already in use by another program. Start with --port to choose another.")
    url = f"http://127.0.0.1:{port}"

    # Order matters: the environment must be complete before isocline.core.config is imported anywhere.
    from isocline.desktop import bootstrap
    from isocline.desktop.search import SearchService
    search = SearchService(data, _any_free_port())
    bootstrap.prepare(port, args.data_dir, search_port=search.port)
    search.start()  # starts in the background; the app does not wait for it
    try:
        bootstrap.run_migrations()
    except Exception as e:
        search.stop()
        return _fatal(f"the database could not be prepared ({e}). Data folder: {data}")

    server = Server(port, args.debug)
    try:
        server.start(url)
    except Exception as e:
        search.stop()
        return _fatal(str(e))
    (data / INSTANCE_FILE).write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")

    try:
        if args.headless:
            print(f"Isocline is running at {url}  (press Ctrl+C to stop)")
            try:
                while server.thread.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        elif args.browser or not _open_window(url, data):
            _wait_in_browser(url, server)
    finally:
        server.stop()
        search.stop()
        try:
            (data / INSTANCE_FILE).unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
