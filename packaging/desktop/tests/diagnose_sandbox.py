"""Finds which sandbox protection prevents Python from starting on this Windows machine.

Runs `print('ok')` with the protections switched on step by step and prints a table. build.ps1 runs this
automatically when the isolation tests fail; paste its output when reporting a problem.

    set ISOCLINE_SANDBOX_RUNTIME=build\\python-runtime
    python packaging\\desktop\\tests\\diagnose_sandbox.py
"""
from __future__ import annotations

import platform
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))

COMBINATIONS = [
    ("no protections (plain process)", dict(appcontainer=False, job_limits=False, ui_limits=False, child_policy=False)),
    ("AppContainer only", dict(appcontainer=True, job_limits=False, ui_limits=False, child_policy=False)),
    ("+ job limits", dict(appcontainer=True, job_limits=True, ui_limits=False, child_policy=False)),
    ("+ UI limits", dict(appcontainer=True, job_limits=True, ui_limits=True, child_policy=False)),
    ("all (+ child-process policy)", dict(appcontainer=True, job_limits=True, ui_limits=True, child_policy=True)),
    ("all except job limits", dict(appcontainer=True, job_limits=False, ui_limits=True, child_policy=True)),
    ("all except UI limits", dict(appcontainer=True, job_limits=True, ui_limits=False, child_policy=True)),
    ("all except child-process policy", dict(appcontainer=True, job_limits=True, ui_limits=True, child_policy=False)),
]


def main() -> int:
    if sys.platform != "win32":
        print("Windows only")
        return 0
    from isocline.desktop.sandbox import appcontainer, runner
    print(f"Windows {platform.version()} | Python {platform.python_version()} | runtime {runner.runtime_dir()}")
    work_root = Path(tempfile.mkdtemp(prefix="isocline-diag-"))
    width = max(len(name) for name, _ in COMBINATIONS)
    for name, opts in COMBINATIONS:
        appcontainer.PROTECTIONS = appcontainer.Protections(**opts)
        try:
            r = runner.run("print('ok')", {}, timeout=20, work_root=work_root)
            status = "OK" if r.get("success") and r.get("stdout", "").strip() == "ok" else f"FAIL: {r.get('error')}"
            if r.get("stderr"):
                status += f" | stderr: {r['stderr'].strip()[-300:]}"
        except Exception as e:  # noqa: BLE001
            status = f"ERROR: {type(e).__name__}: {e}"
        print(f"  {name:<{width}}  {status}")
    appcontainer.PROTECTIONS = appcontainer.Protections()
    return 0


if __name__ == "__main__":
    sys.exit(main())
