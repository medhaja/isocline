"""Desktop mode: startup recovery, the in-process concurrency cap, static UI serving, environment bootstrap."""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from isocline.db.models import Document, KnowledgeBase, Run, Workflow
from isocline.desktop import runtime, ui
from isocline.services import dispatch


async def _run(env, status: str, **kw) -> Run:
    db = env["db"]
    wf = Workflow(project_id=env["project"].id, name="W", graph={"nodes": [], "edges": []}, created_by=env["user"].id)
    db.add(wf)
    await db.flush()
    run = Run(workflow_id=wf.id, project_id=env["project"].id, workspace_id=env["workspace"].id, status=status, input={}, graph_snapshot={"nodes": [], "edges": []}, **kw)
    db.add(run)
    await db.commit()
    return run


async def test_startup_recovers_interrupted_and_queued_runs(env):
    db = env["db"]
    from isocline.db.models import utcnow
    running = await _run(env, "running", heartbeat_at=utcnow(), worker_id="desktop")  # fresh heartbeat: old process
    queued = await _run(env, "queued")
    exhausted = await _run(env, "running", heartbeat_at=utcnow(), recovery_attempts=runtime.MAX_RECOVERY_ATTEMPTS)
    done = await _run(env, "completed")

    await runtime.recover_on_startup()

    enq = db.info["queued"]
    assert str(running.id) in enq and str(queued.id) in enq
    assert str(exhausted.id) not in enq and str(done.id) not in enq
    for r in (running, exhausted):
        await db.refresh(r)
    assert running.heartbeat_at is None and running.recovery_attempts == 1  # claimable immediately
    assert exhausted.status == "failed"


async def test_startup_requeues_interrupted_ingestion(env):
    db = env["db"]
    kb = KnowledgeBase(project_id=env["project"].id, name="KB")
    db.add(kb)
    await db.flush()
    doc = Document(knowledge_base_id=kb.id, project_id=env["project"].id, filename="a.txt", mime="text/plain", size_bytes=1, storage_key="k",
                   status="processing")
    db.add(doc)
    await db.commit()
    ingested: list[str] = []
    dispatch.set_ingest_dispatcher(ingested.append)
    try:
        await runtime.recover_on_startup()
    finally:
        dispatch.set_ingest_dispatcher(None)
    assert ingested == [str(doc.id)]
    await db.refresh(doc)
    assert doc.status == "pending"


async def test_in_process_dispatch_caps_concurrency_and_dedupes(monkeypatch):
    from isocline.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "mode", "desktop")
    monkeypatch.setattr(s, "desktop_concurrency", 2)
    monkeypatch.setattr(dispatch, "_slots", None)
    active = peak = 0
    release = asyncio.Event()

    async def work():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await release.wait()
        active -= 1

    for i in range(5):
        assert dispatch._inline(work, key=f"run:{i}")
    assert dispatch._inline(work, key="run:0")  # duplicate: accepted, not queued twice
    await asyncio.sleep(0.05)
    assert peak == 2 and len(dispatch.inflight()) == 5
    release.set()
    await dispatch.drain(2)
    assert peak == 2 and not dispatch.inflight()
    monkeypatch.setattr(dispatch, "_slots", None)


def test_ui_serves_export_and_never_shadows_api(tmp_path):
    (tmp_path / "index.html").write_text("home")
    (tmp_path / "runs.html").write_text("runs page")
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "index.html").write_text("settings page")
    (tmp_path / "404.html").write_text("missing")
    (tmp_path / "_next" / "static").mkdir(parents=True)
    (tmp_path / "_next" / "static" / "app.js").write_text("js")
    (tmp_path.parent / "secret.txt").write_text("nope")
    app = FastAPI()

    @app.get("/api/v1/meta")
    async def meta():
        return {"ok": True}

    ui.mount(app, str(tmp_path))
    c = TestClient(app)
    assert c.get("/").text == "home"
    assert c.get("/runs").text == "runs page"
    assert c.get("/runs?id=abc").text == "runs page"
    assert c.get("/settings").text == "settings page"
    assert "immutable" in c.get("/_next/static/app.js").headers["cache-control"]
    assert c.get("/api/v1/meta").json() == {"ok": True}
    assert c.get("/api/v1/unknown").status_code == 404 and "missing" not in c.get("/api/v1/unknown").text
    r = c.get("/nope")
    assert r.status_code == 404 and r.text == "missing"
    assert "nope" not in c.get("/..%2Fsecret.txt").text
    old = c.get("/runs/abc-123?tab=trace", follow_redirects=False)
    assert old.status_code == 307 and old.headers["location"] == "/runs/view?id=abc-123&tab=trace"
    assert c.get("/runs/compare", follow_redirects=False).status_code == 404  # not a legacy record URL


def test_bootstrap_prepares_isolated_environment(tmp_path):
    from isocline.desktop import bootstrap
    # bootstrap writes os.environ directly; snapshot and restore it so nothing leaks into other tests.
    saved = dict(os.environ)
    for k in [k for k in os.environ if k.startswith("ISOCLINE_")] + ["OLLAMA_BASE_URL", "SANDBOX_TOKEN", "OPENAI_API_KEY"]:
        os.environ.pop(k, None)
    try:
        _check_bootstrap(bootstrap, tmp_path)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _check_bootstrap(bootstrap, tmp_path):
    (tmp_path / "isocline.env").write_text("OPENAI_API_KEY=sk-test\nISOCLINE_DESKTOP_CONCURRENCY=2\n")
    data = bootstrap.prepare(47321, str(tmp_path))
    assert data == tmp_path
    assert os.environ["ISOCLINE_MODE"] == "desktop"
    assert os.environ["ISOCLINE_DATABASE_URL"].startswith("sqlite+aiosqlite:///")
    assert os.environ["ISOCLINE_PUBLIC_BASE_URL"] == "http://127.0.0.1:47321"
    assert os.environ["OPENAI_API_KEY"] == "sk-test" and os.environ["ISOCLINE_DESKTOP_CONCURRENCY"] == "2"
    assert len(os.environ["ISOCLINE_SECRET_KEY"]) > 40 and os.environ["ISOCLINE_ENCRYPTION_KEY"]
    first = (tmp_path / "secrets.env").read_text()
    bootstrap.ensure_secrets(tmp_path)
    assert (tmp_path / "secrets.env").read_text() == first  # generated once, kept afterwards


def test_source_runs_use_a_separate_data_folder(tmp_path, monkeypatch):
    import sys

    from isocline.desktop import paths
    monkeypatch.delenv("ISOCLINE_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    assert paths.data_dir().name == "Isocline-dev"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.data_dir().name == "Isocline"  # the installed app


async def test_preflight_accepts_search_key_from_environment_and_flags_python_on_desktop(env, monkeypatch):
    from isocline.core.config import get_settings
    from isocline.schemas.workflow import WorkflowGraph
    from isocline.services.validation import validate_environment
    s = get_settings()
    monkeypatch.setattr(s, "search_provider", "tavily")
    g = WorkflowGraph.model_validate({"nodes": [
        {"id": "s", "key": "search", "type": "tool_web_search", "config": {"query": "x"}},
        {"id": "p", "key": "py", "type": "tool_python", "config": {"code": "print(1)"}}], "edges": []})

    async def codes():
        return {i.code for i in await validate_environment(env["db"], g, env["workspace"].id, env["project"].id)}

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert "search_credential_missing" in await codes()
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")  # e.g. from isocline.env in the data folder
    assert "search_credential_missing" not in await codes()

    monkeypatch.setattr(s, "mode", "desktop")
    monkeypatch.delenv("ISOCLINE_DESKTOP_SANDBOX", raising=False)
    from isocline.desktop import sandbox
    monkeypatch.setattr(sandbox, "available", lambda: (False, "the Python runtime is missing"))
    issues = await validate_environment(env["db"], g, env["workspace"].id, env["project"].id)
    py = [i for i in issues if i.code == "sandbox_unavailable"]
    assert py and "Python steps are unavailable: the Python runtime is missing" == py[0].message
