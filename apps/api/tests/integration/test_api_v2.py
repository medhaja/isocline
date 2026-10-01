"""V2 HTTP-level flows (cookies + CSRF + tenant checks)."""
import hashlib
import hmac
import json
import time

from tests.conftest import agent, drain, edge, graph, node, signup


def simple(model="echo", **cfg):
    return graph([node("inp", "input_text", field="topic"), agent("research", model, **cfg), node("out", "output_text")],
                 [edge("inp", "research"), edge("research", "out")])


async def setup(api):
    me = await signup(api)
    ws = me["workspace_id"]
    pid = (await api.post(f"/api/v1/workspaces/{ws}/projects", json={"name": "P"})).json()["id"]
    return ws, pid


async def drain_all(app_env):
    from isocline.services.evaluation import execute_evaluation
    for _ in range(10):
        await drain(app_env["runs"])
        if not app_env["evals"]:
            break
        while app_env["evals"]:
            await execute_evaluation(app_env["evals"].pop(0), executor_factory=True)


async def wf_with(api, pid, g, name="W"):
    return (await api.post(f"/api/v1/projects/{pid}/workflows", json={"name": name, "graph": g})).json()


async def test_plan_preflight_and_context_preview(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple())
    plan = (await api.post(f"/api/v1/workflows/{wf['id']}/plan", json={})).json()
    assert plan["status"] == "READY" and plan["counts"]["agents"] == 1
    assert plan["totals"]["llm_calls"][0] >= 1 and {c["category"] for c in plan["checks"]} >= {"Structure", "Budgets", "Policies"}
    bad = simple()
    bad["settings"]["max_llm_calls"] = 1
    bad["nodes"].insert(2, agent("second"))
    bad["edges"] = [edge("inp", "research"), edge("research", "second"), edge("second", "out")]
    assert (await api.post(f"/api/v1/workflows/{wf['id']}/plan", json={"graph": bad})).json()["status"] == "BLOCKED"
    nid = next(n["id"] for n in wf["graph"]["nodes"] if n["key"] == "research")
    prev = (await api.post(f"/api/v1/workflows/{wf['id']}/nodes/{nid}/context-preview", json={"input": {"topic": "acme"}})).json()
    cats = {c["category"] for c in prev["categories"]}
    assert {"system", "request", "user_input"} <= cats and prev["total_tokens"] > 0


async def test_custom_types_and_edge_types(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    r = await api.post(f"/api/v1/workspaces/{ws}/types", json={"name": "RiskReport", "json_schema": {"risk_score": "number"}})
    assert r.status_code == 201
    g = simple()
    g["nodes"][2]["contract"] = {"inputs": [{"name": "in", "type": "JSON<RiskReport>"}]}
    wf = await wf_with(api, pid, g)
    et = (await api.post(f"/api/v1/workflows/{wf['id']}/edge-types", json={})).json()
    e = next(v for v in et.values() if v.get("target_type"))
    assert e["source_type"] == "Text" and e["ok"] is False


async def test_policy_crud_effective_and_mandatory_rules(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple("tool-user", tools=["calculator"]))
    r = await api.post("/api/v1/policies", json={"name": "Prod", "scope_type": "workspace", "scope_id": ws, "rules": [
        {"kind": "tool", "subject": "calculator", "effect": "deny", "mandatory": True},
        {"kind": "budget", "subject": "max_run_cost", "effect": "limit", "value": 1}]})
    assert r.status_code == 201, r.text
    bad = await api.post("/api/v1/policies", json={"name": "x", "scope_type": "workspace", "scope_id": ws, "rules": [
        {"kind": "budget", "subject": "nope", "effect": "limit", "value": 1}]})
    assert bad.status_code == 400
    eff = (await api.get(f"/api/v1/workflows/{wf['id']}/effective-policy")).json()
    assert eff["budget_clamps"]["max_cost"] == 1 and len(eff["rules"]) == 2
    rid = (await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "x"}})).json()["run_id"]
    await drain(app_env["runs"])
    h = (await api.get(f"/api/v1/runs/{rid}/harness")).json()
    assert any(d["effect"] == "deny" for d in h["policy_decisions"]) and h["plan"]["status"] == "READY"



async def test_webhook_trigger_signature_replay_idempotency(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple())
    assert (await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "webhook", "name": "hook"})).status_code == 400
    await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})
    t = (await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "webhook", "name": "hook",
                                                                  "config": {"payload_schema": {"topic": "string"}}})).json()
    secret, path = t["secret"], t["path"]
    anon = app_env["new"]()
    body = json.dumps({"topic": "acme"}).encode()
    ts = int(time.time())
    sig = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    h = {"X-Isocline-Timestamp": str(ts), "X-Isocline-Signature": sig, "Content-Type": "application/json"}
    assert (await anon.c.post(path, content=body, headers={**h, "X-Isocline-Signature": "sha256=bad"})).status_code == 401
    old = str(ts - 1000)
    assert (await anon.c.post(path, content=body, headers={**h, "X-Isocline-Timestamp": old})).status_code == 401
    r = await anon.c.post(path, content=body, headers=h)
    assert r.status_code == 202, r.text
    assert (await anon.c.post(path, content=body, headers=h)).status_code == 409  # signature replay
    bad = json.dumps({"topic": 5}).encode()
    s2 = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + bad, hashlib.sha256).hexdigest()
    assert (await anon.c.post(path, content=bad, headers={**h, "X-Isocline-Signature": s2})).status_code == 422
    await drain(app_env["runs"])
    run = (await api.get(f"/api/v1/runs/{r.json()['run_id']}")).json()
    assert run["status"] == "completed" and run["trigger"] == "webhook"


async def test_schedule_and_event_triggers(app_env):
    from isocline.db import session as dbs
    from isocline.db.models import utcnow
    from isocline.db.models_v2 import Trigger
    from isocline.services.triggers import fire_due_schedules, next_fire
    from datetime import datetime, timedelta, timezone
    assert next_fire("0 9 * * 1", datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-05T09:00:00+00:00"
    assert next_fire("*/15 * * * *", datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc)).minute == 15
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple())
    await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})
    assert (await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "schedule", "name": "s",
                                                                     "config": {"cron": "61 * * * *"}})).status_code == 400
    t = (await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "schedule", "name": "daily",
                                                                  "config": {"cron": "daily", "timezone": "Asia/Kolkata", "payload": {"topic": "sched"}}})).json()
    async with dbs.sessionmaker()() as db:
        tr = await db.get(Trigger, __import__("uuid").UUID(t["id"]))
        tr.next_run_at = utcnow() - timedelta(minutes=1)
        await db.commit()
        assert await fire_due_schedules(db) == 1
        assert await fire_due_schedules(db) == 0  # slot fired exactly once
    await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "event", "name": "e", "config": {"event_name": "lead.created"}})
    ev = (await api.post(f"/api/v1/workspaces/{ws}/events", json={"name": "lead.created", "correlation_key": "l-1", "payload": {"topic": "lead"}})).json()
    assert len(ev["runs_started"]) == 1
    await drain(app_env["runs"])


async def test_public_callback_endpoint(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    g = graph([node("inp", "input_text", field="topic"), node("job", "wait_webhook"), node("out", "output_json")],
              [edge("inp", "job"), edge("job", "out")])
    wf = await wf_with(api, pid, g)
    rid = (await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "x"}})).json()["run_id"]
    await drain(app_env["runs"])
    h = (await api.get(f"/api/v1/runs/{rid}/harness")).json()
    path = h["waits"][0]["callback_path"]
    anon = app_env["new"]()
    assert (await anon.c.post(path[:-3] + "xyz", json={})).status_code == 401
    assert (await anon.c.post(path, json={"done": True})).json()["status"] == "resumed"
    await drain(app_env["runs"])
    assert (await api.get(f"/api/v1/runs/{rid}")).json()["output"]["result"] == {"done": True}


async def test_experiment_matrix_and_pareto(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple())
    ds = (await api.post(f"/api/v1/projects/{pid}/evaluation-datasets", json={"name": "D", "cases": [
        {"name": "a", "input": {"topic": "acme"}, "evaluators": [{"type": "contains", "values": ["acme"]}]}]})).json()
    nid = next(n["id"] for n in wf["graph"]["nodes"] if n["key"] == "research")
    e = (await api.post(f"/api/v1/workflows/{wf['id']}/experiments", json={"name": "Models", "dataset_id": ds["id"], "node_id": nid,
         "dimensions": {"model": [{"provider": "local_test", "model": "echo"}, {"provider": "local_test", "model": "slow-1"}],
                        "params": [{"temperature": 0}, {"temperature": 0.7}]}})).json()
    assert len(e["variants"]) == 4
    await api.post(f"/api/v1/experiments/{e['id']}/start")
    await drain_all(app_env)
    e = (await api.get(f"/api/v1/experiments/{e['id']}")).json()
    assert e["status"] == "completed" and all(v["metrics"]["pass_rate"] == 1.0 for v in e["variants"])
    fast = [v for v in e["variants"] if "echo" in v["name"]]
    assert all(v["pareto"] for v in fast) and not any(v["pareto"] for v in e["variants"] if "slow" in v["name"])


async def test_playground_contract_tests_gate_publishing(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    g = graph([node("inp", "input_text", field="topic"), agent("research"), agent("scorer", "json", output_schema={"risk_score": "number"}),
               node("out", "output_json")], [edge("inp", "research"), edge("research", "scorer"), edge("scorer", "out")])
    wf = await wf_with(api, pid, g)
    sid = next(n["id"] for n in wf["graph"]["nodes"] if n["key"] == "scorer")
    pgr = await api.post(f"/api/v1/workflows/{wf['id']}/nodes/{sid}/playground", json={"mocks": {"research": "mocked research"}})
    assert pgr.status_code == 202, pgr.text
    pg = pgr.json()
    await drain(app_env["runs"])
    nodes = {n["node_key"]: n for n in (await api.get(f"/api/v1/runs/{pg['run_id']}/nodes")).json()}
    assert nodes["research"]["attempts"][0]["status"] == "mocked" and nodes["research"]["llm_calls"] == 0
    assert "mocked research" in nodes["scorer"]["input"]["user_message"]
    await api.post(f"/api/v1/workflows/{wf['id']}/tests", json={"node_id": sid, "name": "score in range", "mocks": {"research": "r"},
                                                                "assertions": [{"path": "risk_score", "op": "between", "value": [0, 1]}]})
    blocked = await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "contract_tests_failed"
    await api.post(f"/api/v1/workflows/{wf['id']}/tests/run")
    await drain(app_env["runs"])
    tests = (await api.get(f"/api/v1/workflows/{wf['id']}/tests")).json()
    assert tests[0]["last_status"] == "passed" and tests[0]["current"]
    assert (await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})).status_code == 201


async def test_optimizer_proposes_candidate_evaluates_and_applies_to_draft_only(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    g = graph([node("inp", "input_text", field="topic"), agent("research"), agent("financial", prompt="Analyze {{research.output}}"),
               agent("risk", prompt="Assess risks using {{research.output}}"), node("out", "output_text")],
              [edge("inp", "research"), edge("research", "financial"), edge("financial", "risk"), edge("risk", "out")])
    wf = await wf_with(api, pid, g)
    await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})
    for _ in range(3):
        await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "same"}})
    await drain(app_env["runs"])
    o = (await api.post(f"/api/v1/workflows/{wf['id']}/optimize")).json()
    kinds = {r["kind"] for r in o["recommendations"]}
    assert "parallelize" in kinds and "enable_cache" in kinds, kinds
    pars = [r for r in o["recommendations"] if r["kind"] == "parallelize"]
    assert len(pars) == 1 and "Financial" in pars[0]["title"] and "Risk" in pars[0]["title"]  # research→financial is a real dependency
    par = pars[0]
    cand = (await api.post(f"/api/v1/optimizations/{o['id']}/candidate", json={"recommendation_ids": [par["id"]]})).json()
    assert not [i for i in cand["issues"] if i["severity"] == "error"]
    assert any(a["type"] == "merge" for a in cand["diff"]["added"])
    ds = (await api.post(f"/api/v1/projects/{pid}/evaluation-datasets", json={"name": "D", "cases": [{"name": "a", "input": {"topic": "acme"},
                                                                                                         "evaluators": [{"type": "contains", "values": ["acme"]}]}]})).json()
    await api.post(f"/api/v1/optimizations/{o['id']}/evaluate", json={"dataset_id": ds["id"]})
    await drain_all(app_env)
    o2 = (await api.get(f"/api/v1/optimizations/{o['id']}")).json()
    assert o2["status"] == "evaluated" and o2["evaluations"]["candidate"]["pass_rate"] == 1.0
    before = (await api.get(f"/api/v1/workflows/{wf['id']}")).json()
    assert (await api.post(f"/api/v1/optimizations/{o['id']}/apply")).status_code == 200
    after = (await api.get(f"/api/v1/workflows/{wf['id']}")).json()
    assert after["revision"] == before["revision"] + 1 and after["latest_version"] == before["latest_version"]  # never publishes
    v1 = (await api.get(f"/api/v1/workflows/{wf['id']}/versions/1")).json()
    assert not any(n["type"] == "merge" for n in v1["graph"]["nodes"])  # published version untouched


async def test_monitoring_heatmap_lineage_artifacts(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    g = graph([node("inp", "input_text", field="topic"), agent("research"),
               node("out", "output_file", template="{{research.output}}", format="file", filename="report.md")],
              [edge("inp", "research"), edge("research", "out")])
    wf = await wf_with(api, pid, g)
    rid = (await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "acme"}})).json()["run_id"]
    await drain(app_env["runs"])
    mon = (await api.get(f"/api/v1/projects/{pid}/monitoring")).json()
    d = next(t for t in mon["targets"] if t["kind"] == "workflow" and t["workflow_id"] == wf["id"])
    assert d["metrics"]["requests"] == 1 and d["metrics"]["success_rate"] == 1.0
    hm = (await api.get(f"/api/v1/workflows/{wf['id']}/heatmap")).json()
    assert hm["runs_analyzed"] == 1 and any(b["label"] == "Highest latency" for b in hm["bottlenecks"])
    lin = (await api.get(f"/api/v1/runs/{rid}/lineage?field=report")).json()
    assert lin["field"]["produced_by"] == "research" and lin["field"]["precision"] == "exact field mapping"
    arts = (await api.get(f"/api/v1/projects/{pid}/artifacts")).json()
    assert len(arts) == 1 and "storage_key" not in arts[0]
    prev = (await api.get(f"/api/v1/artifacts/{arts[0]['id']}/preview")).json()
    assert prev["type"] == "text" and "acme" in prev["text"]
    dl = await api.get(f"/api/v1/artifacts/{arts[0]['id']}/download")
    assert dl.status_code == 200 and b"acme" in dl.content
    other = app_env["new"]()
    await signup(other, "mallory@example.com")
    assert (await other.get(f"/api/v1/artifacts/{arts[0]['id']}")).status_code == 404


async def test_mcp_registration_is_explicit_and_ssrf_safe(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    assert (await api.post(f"/api/v1/workspaces/{ws}/mcp", json={"name": "local", "endpoint": "file:///etc"})).status_code in (400, 422)
    m = (await api.post(f"/api/v1/workspaces/{ws}/mcp", json={"name": "internal", "endpoint": "http://127.0.0.1:9/mcp"})).json()
    assert m["grants"] == []
    synced = (await api.post(f"/api/v1/mcp/{m['id']}/sync")).json()
    assert synced["status"] == "error"  # private addresses are blocked
    # an agent cannot use an MCP tool that is not allowlisted, even if granted in config
    g = simple("tool-user", tools=["mcp:internal/delete_everything"])
    wf = await wf_with(api, pid, g)
    r = await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "x"}})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["code"] == "mcp_tool_not_allowed"


async def test_access_tokens_for_sdk(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    tok = (await api.post("/api/v1/tokens", json={"name": "ci"})).json()
    assert tok["token"].startswith("isc_pat_")
    sdk = app_env["new"]()
    h = {"Authorization": f"Bearer {tok['token']}"}
    r = await sdk.c.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200
    wf = (await sdk.c.post(f"/api/v1/projects/{pid}/workflows", json={"name": "via sdk", "graph": simple()}, headers=h))
    assert wf.status_code == 201  # bearer tokens are not subject to cookie CSRF
    await api.post(f"/api/v1/tokens/{tok['id']}/revoke")
    assert (await sdk.c.get("/api/v1/auth/me", headers=h)).status_code == 401


async def test_monthly_quota_blocks_runs(app_env):
    from isocline.db import session as dbs
    from isocline.db.models_v2 import WorkspaceQuota
    import uuid
    api = app_env["new"]()
    ws, pid = await setup(api)
    async with dbs.sessionmaker()() as db:
        db.add(WorkspaceQuota(workspace_id=uuid.UUID(ws), monthly_cost_quota=0.0))
        await db.commit()
    wf = await wf_with(api, pid, simple())
    r = await api.post(f"/api/v1/workflows/{wf['id']}/run", json={"input": {"topic": "x"}})
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"


async def test_webhook_shared_token_mode(app_env):
    api = app_env["new"]()
    ws, pid = await setup(api)
    wf = await wf_with(api, pid, simple())
    await api.post(f"/api/v1/workflows/{wf['id']}/publish", json={})
    t = (await api.post(f"/api/v1/projects/{pid}/triggers", json={"workflow_id": wf["id"], "kind": "webhook", "name": "tok",
                                                                  "config": {"auth": "token"}})).json()
    anon = app_env["new"]()
    body = {"topic": "acme"}
    assert (await anon.c.post(t["path"], json=body, headers={"X-Isocline-Token": "wrong"})).status_code == 401
    h = {"X-Isocline-Token": t["secret"], "Idempotency-Key": "order-1"}
    r1 = (await anon.c.post(t["path"], json=body, headers=h)).json()
    r2 = (await anon.c.post(t["path"], json=body, headers=h)).json()
    assert r1["run_id"] == r2["run_id"] and r2["duplicate"]  # idempotent retries
