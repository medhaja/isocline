"""Desktop Python steps: orchestration (work folder, request/result files, limits, parsing, cleanup) and wiring.

Runs everywhere with the unsafe-local backend (no isolation). The isolation itself is Windows-only and is proven by
packaging/desktop/tests/test_sandbox_isolation.py on real Windows during every build."""
from __future__ import annotations

import base64

import pytest

from isocline.desktop import sandbox


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setenv("ISOCLINE_DESKTOP_SANDBOX", "unsafe-local")
    monkeypatch.setenv("ISOCLINE_DATA_DIR", str(tmp_path))
    return tmp_path


def test_runs_code_with_inputs_and_returns_output_files(local):
    r = sandbox.run("import json\nprint(INPUTS['n'] * 2)\nopen('out/r.txt','w').write('hi')", {"n": 21})
    assert r["success"], r
    assert r["stdout"].strip() == "42"
    assert [f["name"] for f in r["files"]] == ["r.txt"] and base64.b64decode(r["files"][0]["base64"]) == b"hi"


def test_errors_are_reported_and_work_folders_removed(local):
    r = sandbox.run("raise ValueError('boom')")
    assert not r["success"] and "ValueError: boom" in r["error"]
    assert not any((local / "sandbox").iterdir())  # nothing left behind


def test_timeout_kills_the_run(local, monkeypatch):
    from isocline.desktop.sandbox import runner
    monkeypatch.setattr(runner, "_launch", lambda argv, work, env, rt, wall, cpu: runner._launch_unsafe(argv, work, env, 1.5))
    r = sandbox.run("while True: pass", timeout=1)
    assert r["timed_out"] and not r["success"] and "time limit" in r["error"]


def test_environment_is_minimal(local, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ISOCLINE_SECRET_KEY", "should-not-leak")
    r = sandbox.run("import os\nprint(sorted(k for k in os.environ if 'KEY' in k or k.startswith('ISOCLINE')))")
    assert r["success"] and r["stdout"].strip() == "[]"


def test_unavailable_off_windows_without_the_test_backend(monkeypatch):
    import sys
    monkeypatch.delenv("ISOCLINE_DESKTOP_SANDBOX", raising=False)
    if sys.platform == "win32":
        pytest.skip("covered by the Windows isolation tests")
    ok, reason = sandbox.available()
    assert not ok and "Windows" in reason
    r = sandbox.run("print(1)")
    assert not r["success"] and "unavailable" in r["error"]


async def test_python_tool_uses_the_local_sandbox_in_desktop_mode(local, monkeypatch):
    from isocline.core.config import get_settings
    from isocline.tools.base import ToolContext
    from isocline.tools.builtin import PythonTool
    monkeypatch.setattr(get_settings(), "mode", "desktop")

    async def no_secret(_):
        return None
    out = await PythonTool().execute({"code": "print(sum(INPUTS['xs']))", "inputs": {"xs": [1, 2, 3]}},
                                     ToolContext(workspace_id="w", project_id="p", run_id=None, get_secret=no_secret))
    assert out["success"] and out["stdout"].strip() == "6"


async def test_preflight_allows_python_when_the_sandbox_is_available(env, local, monkeypatch):
    from isocline.core.config import get_settings
    from isocline.schemas.workflow import WorkflowGraph
    from isocline.services.validation import validate_environment
    monkeypatch.setattr(get_settings(), "mode", "desktop")
    g = WorkflowGraph.model_validate({"nodes": [{"id": "p", "key": "py", "type": "tool_python",
                                                 "config": {"arguments": {"code": "print(1)"}}}], "edges": []})
    codes = {i.code for i in await validate_environment(env["db"], g, env["workspace"].id, env["project"].id)}
    assert "sandbox_unavailable" not in codes
