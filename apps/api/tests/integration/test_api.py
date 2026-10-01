"""HTTP-level tests: auth, CSRF, tenant isolation, workflow lifecycle, runs, approvals, evaluations."""
from tests.conftest import agent, drain, edge, graph, node, signup


def simple_graph(model="echo"):
    return graph([node("inp", "input_text", field="topic"), agent("research", model), node("out", "output_text")],
                 [edge("inp", "research"), edge("research", "out")])


async def setup_project(api):
    me = await signup(api)
    ws = me["workspace_id"]
    r = await api.post(f"/api/v1/workspaces/{ws}/projects", json={"name": "Research"})
    assert r.status_code == 201, r.text
    return ws, r.json()["id"]


async def test_auth_flow_and_csrf(app_env):
    api = app_env["new"]()
    me = await signup(api)
    assert me["user"]["email"] == "alice@example.com"
    assert (await api.get("/api/v1/auth/me")).status_code == 200
    # state change without the CSRF header is rejected
    r = await api.c.post(f"/api/v1/workspaces/{me['workspace_id']}/projects", json={"name": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    await api.post("/api/v1/auth/logout")
    assert (await api.get("/api/v1/auth/me")).status_code == 401
    bad = await api.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    ok = await api.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct-horse-battery"})
    assert ok.status_code == 200


async def test_password_reset_token_single_use(app_env):
    import hashlib
    from sqlalchemy import select
    from isocline.db import session as dbs
    from isocline.db.models import AuthToken
    api = app_env["new"]()
    await signup(api)
    assert (await api.post("/api/v1/auth/forgot-password", json={"email": "alice@example.com"})).status_code == 200
    assert (await api.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})).status_code == 200
    # Inject a known token (the real one is only delivered by email)
    async with dbs.sessionmaker()() as s:
        t = (await s.execute(select(AuthToken).where(AuthToken.kind == "password_reset"))).scalar_one()
        t.token_hash = hashlib.sha256(b"known-token").hexdigest()
        await s.commit()
    r = await api.post("/api/v1/auth/reset-password", json={"token": "known-token", "password": "a-brand-new-password"})
    assert r.status_code == 200
    r = await api.post("/api/v1/auth/reset-password", json={"token": "known-token", "password": "another-new-password"})
    assert r.status_code == 400


async def test_tenant_isolation(app_env):
    alice, bob = app_env["new"](), app_env["new"]()
    ws, pid = await setup_project(alice)
    wf = (await alice.post(f"/api/v1/projects/{pid}/workflows", json={"name": "W", "graph": simple_graph()})).json()
    await signup(bob, "bob@example.com")
    for url in (f"/api/v1/projects/{pid}", f"/api/v1/workflows/{wf['id']}", f"/api/v1/workspaces/{ws}/projects",
                f"/api/v1/workspaces/{ws}/credentials"):
        assert (await bob.get(url)).status_code == 404, url
    assert (await bob.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {}})).status_code == 404


async def test_workflow_lifecycle_and_run(app_env):
    api = app_env["new"]()
    ws, pid = await setup_project(api)
    r = await api.post(f"/api/v1/projects/{pid}/workflows", json={"name": "Company research", "graph": simple_graph()})
    assert r.status_code == 201
    wf = r.json()
    # autosave with optimistic concurrency
    g = wf["graph"]
    g["nodes"][1]["name"] = "Lead researcher"
    r = await api.put(f"/api/v1/workflows/{wf['id']}", json={"graph": g, "revision": wf["revision"]})
    assert r.status_code == 200 and r.json()["revision"] == wf["revision"] + 1
    stale = await api.put(f"/api/v1/workflows/{wf['id']}", json={"graph": g, "revision": wf["revision"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    # validation
    v = (await api.post(f"/api/v1/workflows/{wf['id']}/validate", json={})).json()
    assert v["valid"], v
    # run through the API, execute like a worker, read results back
    r = await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "acme"}})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    await drain(app_env["runs"])
    run = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert run["status"] == "completed" and "acme" in run["output"]["result"]
    nodes = (await api.get(f"/api/v1/runs/{run_id}/nodes")).json()
    assert {n["node_key"] for n in nodes} == {"inp", "research", "out"}
    events = (await api.get(f"/api/v1/runs/{run_id}/events.json")).json()
    assert events[0]["type"] == "RUN_STARTED" and events[-1]["type"] == "RUN_COMPLETED"
    # SSE replays persisted events and ends for a finished run
    sse = await api.get(f"/api/v1/runs/{run_id}/events")
    assert "RUN_COMPLETED" in sse.text and "event: end" in sse.text
    # dashboard reflects the run
    dash = (await api.get(f"/api/v1/workspaces/{ws}/dashboard")).json()
    assert dash["total_runs"] == 1 and dash["success_rate"] == 1.0


async def test_versions_publish_restore_export_import(app_env):
    api = app_env["new"]()
    ws, pid = await setup_project(api)
    wf = (await api.post(f"/api/v1/projects/{pid}/workflows", json={"name": "W", "graph": simple_graph()})).json()
    # add a credential reference then export: it must be stripped
    g = wf["graph"]
    g["nodes"][1]["config"]["model"]["credential_id"] = None
    v1 = await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={"notes": "first"})
    assert v1.status_code == 201 and v1.json()["version"] == 1
    g["nodes"][1]["name"] = "Changed"
    cur = (await api.get(f"/api/v1/workflows/{wf['id']}")).json()
    await api.put(f"/api/v1/workflows/{wf['id']}", json={"graph": g, "revision": cur["revision"]})
    ver = (await api.get(f"/api/v1/workflows/{wf['id']}/versions/1")).json()
    assert ver["graph"]["nodes"][1]["name"] != "Changed"  # published versions are immutable
    restored = (await api.post(f"/api/v1/workflows/{wf['id']}/versions/1/restore")).json()
    assert restored["graph"]["nodes"][1]["name"] != "Changed"
    doc = (await api.get(f"/api/v1/workflows/{wf['id']}/export")).json()
    assert doc["schema_version"] == "2.0" and "credential_id" not in str(doc)
    # V1 documents still import (upgraded in memory; untyped edges become Any)
    v1doc = {**doc, "schema_version": "1.0", "graph": {**doc["graph"], "schema_version": "1.0"}}
    for n in v1doc["graph"]["nodes"]:
        n.pop("contract", None); n.pop("harness", None)
    assert (await api.post(f"/api/v1/projects/{pid}/workflows/import", json={"document": v1doc})).status_code == 201
    imp = await api.post(f"/api/v1/projects/{pid}/workflows/import", json={"document": doc})
    assert imp.status_code == 201 and imp.json()["status"] == "draft"
    assert not app_env["runs"]  # import never executes
    bad = await api.post(f"/api/v1/projects/{pid}/workflows/import", json={"document": {"schema_version": "9.9", "name": "x"}})
    assert bad.status_code == 400


async def test_template_and_human_approval_via_api(app_env):
    api = app_env["new"]()
    ws, pid = await setup_project(api)
    tpls = (await api.get("/api/v1/templates")).json()
    assert any(t["id"] == "investment_research_team" for t in tpls)
    r = await api.post(f"/api/v1/projects/{pid}/workflows", json={
        "name": "Invest", "template_id": "investment_research_team", "model": {"provider": "local_test", "model": "json"}})
    wf = r.json()
    # swap python analyst to the calculator so no sandbox is needed in tests
    for n in wf["graph"]["nodes"]:
        if n["key"] == "python_analyst":
            n["config"]["tools"] = ["calculator"]
    await api.put(f"/api/v1/workflows/{wf['id']}", json={"graph": wf["graph"], "revision": wf["revision"]})
    rr = await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"company": "Example Corp"}})
    assert rr.status_code == 202, rr.text
    run_id = rr.json()["run_id"]
    await drain(app_env["runs"])
    run = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert run["status"] == "waiting" and run["approvals"][0]["status"] == "pending"
    pend = (await api.get(f"/api/v1/workspaces/{ws}/approvals")).json()
    assert len(pend) == 1
    d = await api.post(f"/api/v1/approvals/{pend[0]['id']}/decide", json={"decision": "approved", "comment": "Looks right"})
    assert d.status_code == 200
    await drain(app_env["runs"])
    run = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert run["status"] == "completed", run["error"]
    nodes = {n["node_key"]: n for n in (await api.get(f"/api/v1/runs/{run_id}/nodes")).json()}
    for k in ("financial", "risk", "python_analyst"):
        assert nodes[k]["status"] == "completed"
    assert nodes["rejected"]["status"] == "skipped"
    # replay the manager only
    rp = await api.post(f"/api/v1/runs/{run_id}/replay", json={"node_id": nodes["manager"]["node_id"]})
    assert rp.status_code == 202
    child = rp.json()["run_id"]
    await drain(app_env["runs"])
    cmp = (await api.get(f"/api/v1/runs/compare/{run_id}/{child}")).json()
    assert any(r["key"] == "manager" for r in cmp["nodes"])


async def test_credentials_are_never_returned(app_env):
    api = app_env["new"]()
    ws, _ = await setup_project(api)
    r = await api.post(f"/api/v1/workspaces/{ws}/credentials", json={"provider": "openai", "name": "OpenAI", "value": "sk-test-abcdefghijklmnop1234"})
    assert r.status_code == 201
    body = r.text + (await api.get(f"/api/v1/workspaces/{ws}/credentials")).text
    assert "sk-test-abcdefghijklmnop1234" not in body and "1234" in body  # hint only
    provs = (await api.get(f"/api/v1/providers?workspace_id={ws}")).json()
    assert next(p for p in provs if p["id"] == "openai")["has_credential"]



async def test_evaluation(app_env):
    from isocline.services.evaluation import execute_evaluation
    api = app_env["new"]()
    ws, pid = await setup_project(api)
    wf = (await api.post(f"/api/v1/projects/{pid}/workflows", json={"name": "W", "graph": simple_graph()})).json()
    ds = (await api.post(f"/api/v1/projects/{pid}/evaluation-datasets", json={"name": "Smoke", "cases": [
        {"name": "mentions company", "input": {"topic": "Acme"}, "evaluators": [{"type": "contains", "values": ["acme"]}]},
        {"name": "wrong", "input": {"topic": "Beta"}, "evaluators": [{"type": "contains", "values": ["gamma"]}]},
    ]})).json()
    er = (await api.post(f"/api/v1/workflows/{wf['id']}/evaluate", json={"dataset_id": ds["id"]})).json()
    await execute_evaluation(app_env["evals"].pop(), executor_factory=True)
    res = (await api.get(f"/api/v1/evaluations/{er['id']}")).json()
    assert res["status"] == "completed" and res["summary"]["passed"] == 1 and res["summary"]["failed"] == 1


async def test_ai_generator_heuristic(app_env):
    api = app_env["new"]()
    ws, pid = await setup_project(api)
    gen = (await api.post(f"/api/v1/projects/{pid}/generate-workflow", json={
        "description": "Research a company, run financial and risk analysis in parallel, then a manager writes the final report",
        "model": {"provider": "local_test", "model": "echo"}})).json()
    assert gen["method"] == "heuristic" and not [i for i in gen["issues"] if i["severity"] == "error"], gen["issues"]
    keys = {n["key"] for n in gen["graph"]["nodes"]}
    assert {"research", "financial", "risk", "merge", "manager"} <= keys
    wf = await api.post(f"/api/v1/projects/{pid}/workflows", json={"name": "Gen", "graph": gen["graph"]})
    assert wf.status_code == 201, wf.text


async def test_rate_limit_on_login(app_env):
    api = app_env["new"]()
    codes = [(await api.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope"})).status_code for _ in range(12)]
    assert 429 in codes
