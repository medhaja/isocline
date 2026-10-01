"""Product-level tests for the open-source edition: local mode, end-to-end runs, and a guard that the repository
contains no enterprise-only code."""
from __future__ import annotations

from pathlib import Path

from tests.conftest import agent, drain, edge, graph, node, signup

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2] / "isocline"


async def project(api):
    me = await signup(api)
    r = await api.post(f"{API}/workspaces/{me['workspace_id']}/projects", json={"name": "Acme research"})
    assert r.status_code == 201, r.text
    return me["workspace_id"], r.json()["id"]


def research_graph():
    """input -> parallel(financial, risk) -> merge -> approval -> report"""
    return graph(
        [node("inp", "input_text", key="company", field="company"),
         node("fan", "parallel"),
         agent("fin", key="financial", prompt="Financial view of {{company.output}}"),
         agent("risk", key="risk", prompt="Risk view of {{company.output}}"),
         node("merge", "merge", strategy="named"),
         node("ok", "human_approval", key="review", title="Approve report"),
         node("out", "output_report", key="report", template="{{merge.output}}")],
        [edge("inp", "fan"), edge("fan", "fin"), edge("fan", "risk"), edge("fin", "merge"), edge("risk", "merge"),
         edge("merge", "ok"), edge("ok", "out", "approved")])


async def test_core_parallel_approval_workflow_end_to_end(app_env):
    api = app_env["new"]()
    _, pid = await project(api)
    wf = (await api.post(f"{API}/projects/{pid}/workflows", json={"name": "Parallel research", "graph": research_graph()})).json()
    v = (await api.post(f"{API}/workflows/{wf['id']}/validate", json={})).json()
    assert v["valid"], v
    rr = await api.post(f"{API}/workflows/{wf['id']}/run", json={"input": {"company": "Acme Corp"}})
    assert rr.status_code == 202, rr.text
    run = {"id": rr.json()["run_id"]}
    await drain(app_env["runs"])
    r = (await api.get(f"{API}/runs/{run['id']}")).json()
    assert r["status"] == "waiting", r
    nodes = {n["node_key"]: n for n in (await api.get(f"{API}/runs/{run['id']}/nodes")).json()}
    assert nodes["financial"]["status"] == nodes["risk"]["status"] == "completed"
    approvals = (await api.get(f"{API}/runs/{run['id']}/approvals")).json()
    assert len(approvals) == 1
    d = await api.post(f"{API}/approvals/{approvals[0]['id']}/decide", json={"decision": "approved"})
    assert d.status_code == 200, d.text
    await drain(app_env["runs"])
    r = (await api.get(f"{API}/runs/{run['id']}")).json()
    assert r["status"] == "completed", r
    assert r["llm_calls"] == 2


async def test_local_mode_first_account_owns_install_and_signup_closes(app_env, monkeypatch):
    from isocline.core.config import get_settings
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    first, second = app_env["new"](), app_env["new"]()
    me = await signup(first, "owner@example.com")
    assert me["user"]["is_admin"] is True
    projects = (await first.get(f"{API}/workspaces/{me['workspace_id']}/projects")).json()
    assert [p["name"] for p in projects] == ["Default project"]
    r = await second.post(f"{API}/auth/register", json={"email": "stranger@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "signup_closed"
    assert (await first.get(f"{API}/meta")).json()["signup"] == "first_account_only"


async def test_bootstrap_admin_is_created_once(app_env, monkeypatch):
    from sqlalchemy import select
    from isocline.core.config import get_settings
    from isocline.db import session as dbs
    from isocline.db.models import User
    from isocline.db.seed import bootstrap_admin
    monkeypatch.setattr(get_settings(), "bootstrap_admin_email", "Admin@Example.com")
    monkeypatch.setattr(get_settings(), "bootstrap_admin_password", "a-long-local-password")
    async with dbs.sessionmaker()() as db:
        await bootstrap_admin(db)
        await bootstrap_admin(db)
        users = (await db.execute(select(User))).scalars().all()
        assert [(u.email, u.is_admin) for u in users] == [("admin@example.com", True)]
    api = app_env["new"]()
    ok = await api.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "a-long-local-password"})
    assert ok.status_code == 200


async def test_validation_and_publish_work_in_a_project_with_a_knowledge_base(app_env):
    """Regression: validate_environment read `.id` from the UUIDs of a scalar select, so every workflow in a project
    that had a knowledge base failed to validate, publish or run with a 500."""
    api = app_env["new"]()
    _, pid = await project(api)
    kb = await api.post(f"{API}/projects/{pid}/knowledge-bases", json={"name": "Handbook"})
    assert kb.status_code == 201, kb.text
    rag = agent("a", key="answer", knowledge_base_ids=[kb.json()["id"]])
    g = graph([node("inp", "input_text", field="topic"), rag, node("out", "output_text")], [edge("inp", "a"), edge("a", "out")])
    wf = (await api.post(f"{API}/projects/{pid}/workflows", json={"name": "RAG", "graph": g})).json()
    v = await api.post(f"{API}/workflows/{wf['id']}/validate", json={})
    assert v.status_code == 200 and v.json()["valid"], v.text
    assert (await api.post(f"{API}/workflows/{wf['id']}/publish", json={"notes": "v1"})).status_code == 201


async def test_meta_and_openapi(app_env):
    api = app_env["new"]()
    m = (await api.get(f"{API}/meta")).json()
    assert m["edition"] == "oss" and "modules" not in m
    paths = set((await api.get("/api/openapi.json")).json()["paths"])
    for core in ("/api/v1/workflows/{workflow_id}/run", "/api/v1/runs/{run_id}/resume", "/api/v1/runs/{run_id}/compensate",
                 "/api/v1/approvals/{approval_id}/decide", "/api/v1/knowledge-bases/{kb_id}/search",
                 "/api/v1/workflows/{workflow_id}/nodes/{node_id}/playground", "/api/v1/projects/{project_id}/generate-workflow"):
        assert core in paths, core
    removed = [p for p in paths if "deployment" in p or "/environments" in p or p.endswith("/assistant") or "/releases" in p]
    assert not removed, removed


def test_repository_contains_no_enterprise_code():
    """The open-source repository ships the OSS product only."""
    forbidden_files = ["services/workforce.py", "services/canary.py", "services/shadow.py", "services/broker.py",
                       "services/browser.py", "services/computer.py", "engine/team_runtime.py", "db/models_v3.py",
                       "db/models_v31.py", "db/models_v32.py", "api/routes/workforce.py", "api/routes/intelligence.py",
                       "api/routes/action.py", "core/modules.py"]
    assert not [f for f in forbidden_files if (ROOT / f).exists()]
    words = ("AgentVersion", "CanaryDeployment", "ShadowDeployment", "CapabilityRequest", "TeamRuntime", "SecretMetadata")
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") for w in words if w in p.read_text()]
    assert not offenders, offenders
