"""Proves the desktop Python sandbox on real Windows: code must not be able to escape.

Run by packaging/desktop/build.ps1 (and therefore by the GitHub Actions release build) against the freshly built
runtime; a failing test fails the build. Every escape attempt is made by the sandboxed code itself, which prints
BLOCKED or ESCAPED, so a test can only pass if Windows refused the operation.

    set ISOCLINE_SANDBOX_RUNTIME=build\\python-runtime
    python -m pytest packaging\\desktop\\tests -q
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the AppContainer sandbox is Windows-only")

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))


def run(code: str, tmp_path: Path, inputs: dict | None = None, timeout: int = 30) -> dict:
    from isocline.desktop.sandbox import runner
    return runner.run(code, inputs or {}, timeout=timeout, work_root=tmp_path / "work")


def attempt(body: str) -> str:
    """Wraps an escape attempt: prints ESCAPED if the operation worked, BLOCKED <error> if Windows refused it."""
    lines = "\n".join("    " + line for line in body.strip().splitlines())
    return f"try:\n{lines}\n    print('ESCAPED')\nexcept BaseException as e:\n    print('BLOCKED', type(e).__name__, e)\n"


def assert_blocked(r: dict):
    out = r.get("stdout", "")
    assert "BLOCKED" in out and "ESCAPED" not in out, r


@pytest.fixture(scope="session", autouse=True)
def runtime_present():
    from isocline.desktop.sandbox import runner
    if runner.runtime_dir() is None:
        pytest.fail("No sandbox runtime: set ISOCLINE_SANDBOX_RUNTIME to the built python-runtime folder")


# ------------------------------------------------------------------------------------------------- it works at all
def test_runs_code_with_inputs(tmp_path):
    r = run("print(INPUTS['a'] + INPUTS['b'])", tmp_path, {"a": 2, "b": 3})
    assert r["success"] and r["stdout"].strip() == "5", r


def test_data_science_stack_and_output_files(tmp_path):
    code = """
import numpy as np, pandas as pd, scipy.stats as st, matplotlib.pyplot as plt
df = pd.DataFrame({"x": np.arange(10), "y": np.arange(10) ** 2})
print(round(float(st.pearsonr(df.x, df.y)[0]), 3))
df.plot(x="x", y="y"); plt.savefig("out/chart.png")
"""
    r = run(code, tmp_path, timeout=60)
    assert r["success"], r
    assert r["stdout"].strip() == "0.963"
    assert [f["name"] for f in r["files"]] == ["chart.png"]


# ------------------------------------------------------------------------------------------------------- files
def test_cannot_read_files_outside_its_folder(tmp_path):
    secret = tmp_path / "secret.txt"  # stands in for the user's documents and Isocline's database/secrets
    secret.write_text("top secret")
    assert_blocked(run(attempt(f"print(open({str(secret)!r}).read())"), tmp_path))


def test_cannot_list_the_user_profile(tmp_path):
    profile = os.environ["USERPROFILE"]
    assert_blocked(run(attempt(f"import os\nprint(os.listdir(os.path.join({profile!r}, 'Documents')))"), tmp_path))


def test_cannot_write_outside_its_folder(tmp_path):
    target = Path(os.environ["USERPROFILE"]) / "isocline-sandbox-escape.txt"
    try:
        assert_blocked(run(attempt(f"open({str(target)!r}, 'w').write('x')"), tmp_path))
        assert not target.exists()
    finally:
        target.unlink(missing_ok=True)


def test_cannot_see_other_runs(tmp_path):
    assert_blocked(run(attempt("import os\nprint(os.listdir('..'))"), tmp_path))


def test_cannot_modify_the_runtime(tmp_path):
    from isocline.desktop.sandbox import runner
    harness = runner.runtime_dir() / "harness.py"
    assert_blocked(run(attempt(f"open({str(harness)!r}, 'a').write('# tampered')"), tmp_path))


# ----------------------------------------------------------------------------------------------------- network
def test_cannot_reach_localhost(tmp_path):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(15)
    port = srv.getsockname()[1]
    accepted = []
    t = threading.Thread(target=lambda: accepted.append(_accept(srv)), daemon=True)
    t.start()
    try:
        assert_blocked(run(attempt(f"import socket\nsocket.create_connection(('127.0.0.1', {port}), timeout=5)"), tmp_path))
        t.join(1)
        assert accepted in ([], [None])  # Isocline's own API on 127.0.0.1 is unreachable too
    finally:
        srv.close()


def _accept(srv):
    try:
        return srv.accept()
    except OSError:
        return None


def test_cannot_reach_the_internet(tmp_path):
    assert_blocked(run(attempt("import socket\nsocket.create_connection(('1.1.1.1', 443), timeout=5)"), tmp_path))


def test_cannot_resolve_names(tmp_path):
    assert_blocked(run(attempt("import socket\nprint(socket.getaddrinfo('example.com', 443))"), tmp_path))


# ------------------------------------------------------------------------------------------------ processes etc.
def test_cannot_start_programs(tmp_path):
    assert_blocked(run(attempt("import subprocess\nprint(subprocess.run(['cmd.exe', '/c', 'echo hi'], capture_output=True).stdout)"), tmp_path))


def test_environment_has_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    r = run("import os\nprint(sorted(os.environ))", tmp_path)
    assert r["success"] and "OPENAI_API_KEY" not in r["stdout"] and "PATH" not in r["stdout"].split("'"), r


# ------------------------------------------------------------------------------------------------------ limits
def test_runaway_code_is_killed(tmp_path):
    start = time.monotonic()
    r = run("while True:\n    pass", tmp_path, timeout=3)
    assert r["timed_out"] and not r["success"], r
    assert time.monotonic() - start < 20


def test_memory_is_limited(tmp_path):
    r = run(attempt("x = bytearray(3 * 1024 ** 3)"), tmp_path)
    assert "MemoryError" in r.get("stdout", "") + str(r.get("error")), r


def test_work_folder_is_removed(tmp_path):
    run("open('left.txt','w').write('x')", tmp_path)
    assert not [p for p in (tmp_path / "work").iterdir() if p.is_dir()]


# --------------------------------------------------------------------------------------------- reinstall recovery
def test_recovers_after_reinstall_removed_runtime_access(tmp_path):
    """A reinstall recreates the runtime folder without the sandbox's read permission while file dates stay the same.
    The next run must notice and grant it again (this used to fail with 'python312.dll was not found')."""
    from isocline.desktop.sandbox import appcontainer, runner
    rt = runner.runtime_dir()
    sid = appcontainer.container_sid()
    appcontainer.revoke(rt, sid)
    assert not appcontainer.has_access(rt, sid) or appcontainer.has_access(rt, appcontainer.all_application_packages_sid())
    r = run("import numpy\nprint('ok')", tmp_path)
    assert r["success"] and r["stdout"].strip() == "ok", r
    assert appcontainer.has_access(rt, sid)
