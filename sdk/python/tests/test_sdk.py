"""SDK + CLI against a real API app (SQLite, in-process runs)."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[3] / "apps" / "api"
sys.path.insert(0, str(API))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.mkdtemp()
os.environ.update({"ISOCLINE_ENV": "development", "ISOCLINE_DATABASE_URL": f"sqlite+aiosqlite:///{_tmp}/sdk.db",
                   "ISOCLINE_INLINE_WORKER": "true", "ISOCLINE_REDIS_URL": "redis://127.0.0.1:6399/0",
                   "ISOCLINE_STORAGE_LOCAL_PATH": f"{_tmp}/files"})


@pytest.fixture(scope="module")
def client():
    import subprocess
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API, check=True, capture_output=True, env=os.environ)
    from fastapi.testclient import TestClient
    from isocline.main import create_app
    from isocline_sdk import Isocline
    with TestClient(create_app()) as tc:
        r = tc.post("/api/v1/auth/register", json={"email": "sdk@example.com", "password": "correct-horse-battery"})
        ws = r.json()["workspace_id"]
        csrf = tc.cookies.get("isc_csrf")
        pid = tc.post(f"/api/v1/workspaces/{ws}/projects", json={"name": "SDK"}, headers={"X-CSRF-Token": csrf}).json()["id"]
        tok = tc.post("/api/v1/tokens", json={"name": "sdk"}, headers={"X-CSRF-Token": csrf}).json()["token"]
        tc.cookies.clear()
        yield Isocline(base_url="http://testserver", token=tok, http_client=tc), pid, tok, tc


def build():
    from isocline_sdk import Workflow
    wf = Workflow("SDK flow")
    topic = wf.input("topic")
    research = wf.agent("research", prompt="Research {{input.topic}}", model="local_test/echo")
    out = wf.output("out")
    topic >> research >> out
    return wf


def test_dsl_matches_editor_schema():
    g = build().to_graph()
    assert g["schema_version"] == "2.0" and [n["type"] for n in g["nodes"]] == ["input_text", "agent", "output_text"]
    from isocline.schemas.workflow import WorkflowGraph
    WorkflowGraph.model_validate(g)


def test_sdk_create_run_wait_stream_trace(client):
    c, pid, _, _ = client
    wf = c.workflows.create(pid, "SDK flow", build())
    run = c.workflows.run("SDK flow", {"topic": "acme"}, project=pid).wait(timeout=30, poll=0.2)
    assert run.status == "completed" and "acme" in run.output
    types = [e["type"] for e in c.runs.get(run.id).events()]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_COMPLETED"
    assert run.trace()["plan"]["status"] == "READY"
    assert c.workflows.plan(wf["id"])["counts"]["agents"] == 1


def test_cli_validate_run_and_exit_codes(client, capsys, monkeypatch):
    c, pid, tok, tc = client
    from isocline_sdk import cli
    monkeypatch.setattr(cli, "_client", lambda args: c)
    f = Path(_tmp) / "wf.json"
    f.write_text(json.dumps(build().to_document()))
    assert cli.main(["validate", str(f), "--project", pid]) == 0
    bad = build().to_document()
    bad["graph"]["nodes"][1]["config"]["model"] = {"provider": "", "model": ""}
    f.write_text(json.dumps(bad))
    assert cli.main(["validate", str(f), "--project", pid]) == 1
    assert cli.main(["run", "SDK flow", "--project", pid, "--input", '{"topic": "cli"}']) == 0
    assert "cli" in capsys.readouterr().out

