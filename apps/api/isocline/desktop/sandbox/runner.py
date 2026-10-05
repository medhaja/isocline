"""Platform-independent part of the desktop Python sandbox: runtime discovery, the per-run work folder, the request
and result files, limits and result parsing. The isolation itself is in appcontainer.py (Windows)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

MARK = "__AF_SANDBOX__"  # the harness prints its JSON result after this marker
MAX_TIMEOUT = 120
MEMORY_MB = 1024  # per process; pandas + scipy imports alone need a few hundred MB
MAX_PARALLEL = 2
_slots = threading.BoundedSemaphore(MAX_PARALLEL)

# Development and CI only (never set by the app): run without isolation so the orchestration can be tested on
# Linux/macOS. "unsafe-local" makes Python steps run as the current user with full access.
UNSAFE_LOCAL = "unsafe-local"


@dataclass
class Runtime:
    python: Path  # interpreter
    root: Path    # folder with boot.py and harness.py (read-only to the sandbox)


@dataclass
class Outcome:
    exit_code: int | None
    timed_out: bool
    elapsed: float


def mode() -> str:
    return os.environ.get("ISOCLINE_DESKTOP_SANDBOX", "appcontainer")


def runtime_dir() -> Path | None:
    """The bundled sandbox runtime: ISOCLINE_SANDBOX_RUNTIME, the packaged app's python-runtime folder, or
    build/python-runtime in a source checkout (created by build.ps1)."""
    from isocline.desktop import paths
    candidates = []
    if os.environ.get("ISOCLINE_SANDBOX_RUNTIME"):
        candidates.append(Path(os.environ["ISOCLINE_SANDBOX_RUNTIME"]))
    candidates.append(paths.resource_root() / "python-runtime")
    if not paths.frozen():
        candidates.append(paths.resource_root().parents[1] / "build" / "python-runtime")
    for c in candidates:
        if (c / "python.exe").is_file() and (c / "boot.py").is_file():
            return c
    return None


def _runtime() -> Runtime | None:
    if mode() == UNSAFE_LOCAL:
        return Runtime(Path(sys.executable), _unsafe_root())
    rt = runtime_dir()
    return Runtime(rt / "python.exe", rt) if rt else None


def _unsafe_root() -> Path:
    """For the unsafe-local test mode: boot.py and harness.py side by side in a temp folder."""
    root = Path(os.environ.get("TMPDIR") or "/tmp") / "isocline-sandbox-unsafe-root"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("boot.py"), root / "boot.py")
    harness = Path(__file__).resolve().parents[5] / "workers" / "python-sandbox" / "harness.py"
    shutil.copyfile(harness, root / "harness.py")
    return root


def available() -> tuple[bool, str]:
    """(usable, reason when not)."""
    if mode() == UNSAFE_LOCAL:
        return True, ""
    if sys.platform != "win32":
        return False, "Python steps in the desktop app need Windows 10 or later"
    if sys.getwindowsversion().build < 16299:  # Windows 10 1709: AppContainer child-process policy
        return False, "Python steps need Windows 10 version 1709 or later"
    if runtime_dir() is None:
        return False, "the Python runtime is missing from this installation; reinstall Isocline"
    return True, ""


def _work_root() -> Path:
    from isocline.desktop import paths
    return paths.data_dir() / "sandbox"


def _env(work: Path) -> dict[str, str]:
    """A minimal environment: nothing from Isocline's own environment (keys, tokens, PATH) reaches the code."""
    env = {
        "TEMP": str(work / "tmp"), "TMP": str(work / "tmp"),
        "USERPROFILE": str(work), "HOME": str(work), "APPDATA": str(work / "tmp"), "LOCALAPPDATA": str(work / "tmp"),
        "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(work / "mpl"),
        "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
        "PYTHONIOENCODING": "utf-8",
    }
    for k in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


# NTSTATUS codes a sandboxed process can end with before running any Python.
_STATUS = {
    0xC0000142: "the Python runtime failed to initialize inside the sandbox (STATUS_DLL_INIT_FAILED)",
    0xC0000135: "a DLL of the Python runtime was not found or not readable (STATUS_DLL_NOT_FOUND)",
    0xC0000022: "access denied while starting the Python runtime (STATUS_ACCESS_DENIED)",
    0xC0000005: "the Python runtime crashed (STATUS_ACCESS_VIOLATION)",
    0xC0000409: "the Python runtime stopped itself (STATUS_STACK_BUFFER_OVERRUN / fail-fast)",
    0xC0000017: "not enough memory (STATUS_NO_MEMORY)",
}


def describe_exit(code: int | None) -> str:
    if code is None:
        return "no exit code"
    if code in _STATUS:
        return f"{_STATUS[code]}, exit code 0x{code:08X}"
    return f"exit code {code}" + (f" (0x{code:08X})" if code > 0xFFFF else "")


def _parse(work: Path, outcome: Outcome, timeout: int) -> dict:
    if outcome.timed_out:
        return {"success": False, "stdout": "", "stderr": "", "files": [], "timed_out": True,
                "error": f"Execution exceeded the {timeout}s time limit and was killed"}
    text = _read(work / "result.txt")
    if MARK in text:
        try:
            return {**json.loads(text.rsplit(MARK, 1)[1].strip()), "timed_out": False}
        except ValueError:
            pass
    err = _read(work / "stderr.txt")[-4000:]
    return {"success": False, "stdout": text[-4000:], "stderr": err, "files": [], "timed_out": False,
            "error": f"Sandbox exited: {describe_exit(outcome.exit_code)}" + (" (memory limit exceeded?)" if "MemoryError" in err else "")}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run(code: str, inputs: dict | None = None, timeout: int = 30, work_root: Path | None = None) -> dict:
    """Runs code in a fresh sandbox and returns the harness result. Blocking."""
    ok, reason = available()
    if not ok:
        return {"success": False, "stdout": "", "stderr": "", "files": [], "timed_out": False,
                "error": f"Python steps are unavailable: {reason}"}
    rt = _runtime()
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    root = work_root or _work_root()
    root.mkdir(parents=True, exist_ok=True)
    work = root / uuid.uuid4().hex
    with _slots:
        try:
            (work / "tmp").mkdir(parents=True)
            (work / "mpl").mkdir()
            cache = rt.root / "mplcache"  # matplotlib font cache built at packaging time: saves seconds per run
            if cache.is_dir():
                for f in cache.glob("*.json"):
                    shutil.copyfile(f, work / "mpl" / f.name)
            (work / "request.json").write_text(json.dumps({"code": code, "inputs": inputs or {}}), encoding="utf-8")
            argv = [str(rt.python), "-I", "-B", "-X", "utf8", str(rt.root / "boot.py")]
            # Interpreter start-up and imports count against the limit too; allow a little extra wall time for them.
            outcome = _launch(argv, work, _env(work), rt, wall=timeout + 5, cpu=timeout + 5)
            return _parse(work, outcome, timeout)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _launch(argv: list[str], work: Path, env: dict, rt: Runtime, wall: float, cpu: float) -> Outcome:
    if mode() == UNSAFE_LOCAL:
        return _launch_unsafe(argv, work, env, wall)
    from isocline.desktop.sandbox import appcontainer
    return appcontainer.launch(argv, work, env, runtime_root=rt.root, wall_seconds=wall, cpu_seconds=cpu,
                               memory_mb=MEMORY_MB)


def _launch_unsafe(argv: list[str], work: Path, env: dict, wall: float) -> Outcome:
    import subprocess
    start = time.monotonic()
    full_env = {**env, "PATH": os.environ.get("PATH", "")}
    try:
        p = subprocess.run(argv, cwd=work, env=full_env, timeout=wall, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return Outcome(p.returncode, False, time.monotonic() - start)
    except subprocess.TimeoutExpired:
        return Outcome(None, True, time.monotonic() - start)


async def execute(code: str, inputs: dict | None = None, timeout: int = 30) -> dict:
    return await asyncio.to_thread(run, code, inputs, timeout)
