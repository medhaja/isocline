"""Coverage for V2 paths that previously had no test: context strategies, recovery actions, SLA breach modes,
compensation execution, drift, MCP calls, Goal Mode enforcement/replanning, approval timeouts, file triggers,
rejected tool approvals, artifact consumers, sub-workflow failure, optimizer cost rules."""
import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from isocline.db import session as dbs
from isocline.db.models import Approval, Document, ModelPricing, Run, ToolRun, WorkflowVersion, utcnow
from isocline.db.models_v2 import (
    ArtifactUsage, CompensationAction, DriftEvent, GoalPlan, McpServer,
    Trigger,
)
from tests.conftest import agent, edge, graph, make_workflow, node, node_runs, reload_run, run_graph
from tests.integration.test_harness import add_policy, decide, execute, seq


# ------------------------------------------------------------------ context engineering strategies
async def test_context_extract_and_drop_strategies_are_traced(env):
    relevant = "Acme revenue grew 12% in Q3 driven by cloud sales."
    noise = "\n\n".join(f"Unrelated paragraph {i} about gardening and weather patterns." for i in range(400))
    g = graph([node("inp", "input_text", field="topic"), agent("research", prompt="Collect notes"),
               agent("writer", prompt="What happened to Acme revenue?",
                     context={"max_context_tokens": 800, "include_run_input": True,
                              "sources": {"upstream": {"strategy": "extract"}, "user_input": {"strategy": "drop"}}}),
               node("out", "output_text")],
              [edge("inp", "research"), edge("research", "writer"), edge("writer", "out")])
    run, status, _, _ = await run_graph(env, g, {"topic": relevant + "\n\n" + noise})
    assert status == "completed"
    trace = {t["category"]: t for t in (await node_runs(run.id))["writer"].input["context_trace"]}
    assert trace["user_input"]["action"] == "dropped"
    assert trace["upstream"]["action"] in ("extracted", "kept")
    assert sum(t["tokens_after"] for t in trace.values()) <= 850


async def test_context_summarize_makes_a_counted_model_call(env):
    g = graph([node("inp", "input_text", field="topic"),
               agent("writer", prompt="Write", context={"max_context_tokens": 600, "include_run_input": False,
                                                          "sources": {"upstream": {"strategy": "summarize"}}}),
               node("out", "output_text")],
              [edge("inp", "writer"), edge("writer", "out")])
    run, status, _, _ = await run_graph(env, g, {"topic": "acme " * 3000})
    assert status == "completed"
    trace = {t["category"]: t for t in (await node_runs(run.id))["writer"].input["context_trace"]}
    assert trace["upstream"]["action"] == "summarized"
    r = await reload_run(env, run.id)
    assert r.llm_calls == 2  # the writer + the summarization call, both inside the run budget


# ------------------------------------------------------------------ recovery actions
async def test_recovery_route_error_takes_error_branch(env):
    a = agent("research", "fail", retry={"retries": 0})
    a["harness"] = {"recovery": [{"when": ["unavailable"], "actions": ["route_error"]}]}
    g = graph([node("inp", "input_text", field="topic"), a, node("ok", "output_text"), node("err", "output_text", template="fallback path")],
              [edge("inp", "research"), edge("research", "ok"), edge("research", "err", "error")])
    run, status, _, _ = await run_graph(env, g)
    nrs = await node_runs(run.id)
    assert status == "completed" and nrs["err"].status == "completed" and nrs["ok"].status == "skipped"


async def test_recovery_degrade_continues_and_reduce_context_is_recorded(env):
    a = agent("research", "fail", retry={"retries": 0})
    a["harness"] = {"recovery": [{"when": ["any"], "actions": ["reduce_context", "degrade"]}]}
    g = graph([node("inp", "input_text", field="topic"), a, node("out", "output_text", template="done")],
              [edge("inp", "research"), edge("research", "out")])
    run, status, _, _ = await run_graph(env, g)
    nr = (await node_runs(run.id))["research"]
    assert status == "completed" and nr.status == "failed"
    recoveries = [x["error"].get("recovery") for x in nr.attempts if x.get("status") == "failed"]
    assert recoveries[:2] == ["reduce_context", "degrade"]


# ------------------------------------------------------------------ SLA breach modes
async def test_sla_token_breach_alert_and_fail(env):
    run, status, bus, _ = await run_graph(env, seq(harness={"sla": {"max_tokens": 1, "on_breach": "alert"}}))
    assert status == "completed"
    assert any(e["type"] == "NODE_SLA_BREACH" for e in bus.events[str(run.id)])
    async with dbs.sessionmaker()() as s:
        ev = (await s.execute(select(DriftEvent).where(DriftEvent.metric == "sla_breach"))).scalars().all()
    assert ev and ev[0].primary_node_key == "research"
    run2, status2, _, _ = await run_graph(env, seq(harness={"sla": {"max_tokens": 1, "on_breach": "fail"}}))
    assert status2 == "failed" and "SLA breached" in (await reload_run(env, run2.id)).error["message"]


async def test_sla_breach_fallback_uses_the_fallback_model(env):
    a = seq(harness={"sla": {"max_tokens": 1, "on_breach": "fallback"}})
    a["nodes"][1]["config"]["fallbacks"] = [{"provider": "local_test", "model": "json"}]
    run, status, _, _ = await run_graph(env, a)
    assert (await node_runs(run.id))["research"].model == "json"


# ------------------------------------------------------------------ compensation executes in reverse order
async def test_compensation_runs_in_reverse_when_enabled(env, monkeypatch):
    from isocline.tools.builtin import TOOLS
    calls = []

    async def fake_http(args, ctx):
        calls.append(args["url"])
        return {"status": 200}
    monkeypatch.setattr(TOOLS["http_request"], "execute", fake_http)
    nodes = [node("inp", "input_text", field="topic")]
    for k in ("first", "second"):
        n = node(k, "tool_calculator", arguments={"expression": "1+1"})
        n["harness"] = {"compensation": {"tool": "http_request", "arguments": {"method": "DELETE", "url": f"https://api.example.com/{k}"}}}
        nodes.append(n)
    nodes += [agent("boom", "fail", retry={"retries": 0}), node("out", "output_text")]
    g = graph(nodes, [edge("inp", "first"), edge("first", "second"), edge("second", "boom"), edge("boom", "out")])
    g["settings"]["compensation_enabled"] = True
    run, status, bus, _ = await run_graph(env, g)
    assert status == "failed"
    assert calls == ["https://api.example.com/second", "https://api.example.com/first"]
    async with dbs.sessionmaker()() as s:
        rows = (await s.execute(select(CompensationAction).where(CompensationAction.run_id == run.id))).scalars().all()
    assert {r.status for r in rows} == {"succeeded"}
    assert any(e["type"] == "COMPENSATION_COMPLETED" for e in bus.events[str(run.id)])


async def test_compensation_is_not_automatic_by_default(env, monkeypatch):
    from isocline.tools.builtin import TOOLS
    calls = []

    async def fake_http(args, ctx):
        calls.append(args)
        return {}
    monkeypatch.setattr(TOOLS["http_request"], "execute", fake_http)
    n = node("create", "tool_calculator", arguments={"expression": "1+1"})
    n["harness"] = {"compensation": {"tool": "http_request", "arguments": {"method": "DELETE", "url": "https://api.example.com/x"}}}
    g = graph([node("inp", "input_text", field="topic"), n, agent("boom", "fail", retry={"retries": 0}), node("out", "output_text")],
              [edge("inp", "create"), edge("create", "boom"), edge("boom", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "failed" and calls == []


# ------------------------------------------------------------------ drift detection
async def test_drift_detection_against_published_version_baseline(env):
    from isocline.services.monitoring import detect_drift
    db = env["db"]
    wf = await make_workflow(env, seq())
    released = utcnow() - timedelta(days=10)  # baseline = the week after the latest published version
    v = WorkflowVersion(workflow_id=wf.id, version=1, graph=wf.graph, created_at=released)
    db.add(v)
    await db.flush()

    def mk(when, status, cost, latency):
        return Run(workspace_id=env["workspace"].id, project_id=env["project"].id, workflow_id=wf.id, workflow_version_id=v.id,
                   graph_snapshot=wf.graph, settings={}, input={}, trigger="api", status=status, cost_usd=cost,
                   created_at=when, started_at=when, finished_at=when + timedelta(seconds=latency))
    for i in range(10):  # baseline: cheap, fast, healthy
        db.add(mk(released + timedelta(days=1, hours=i), "completed", 0.01, 2))
    for i in range(10):  # last 24h: 3× cost, 4× latency, 40% failures
        db.add(mk(utcnow() - timedelta(hours=i + 1), "failed" if i < 4 else "completed", 0.03, 8))
    await db.commit()
    events = await detect_drift(db, wf.id)
    metrics = {x.metric for x in events}
    assert {"cost_per_run", "latency_p95_s", "failure_rate"} <= metrics
    assert next(x for x in events if x.metric == "failure_rate").severity == "critical"
    assert await detect_drift(db, wf.id) == []  # one alert per metric per day


# ------------------------------------------------------------------ MCP tool calls
async def _mcp(env, allowed):
    env["db"].add(McpServer(workspace_id=env["workspace"].id, name="crm", endpoint="https://mcp.example.com/mcp", allowed_tools=allowed,
                            tools=[{"name": "lookup", "description": "Find a customer", "annotations": {"readOnlyHint": True},
                                    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}}], status="ok"))
    await env["db"].commit()


async def test_mcp_tool_is_called_through_the_harness(env, monkeypatch):
    from isocline.services.mcp import McpClient
    seen = []

    async def fake_call(self, name, args):
        seen.append((name, args))
        return {"content": [{"type": "text", "text": "customer #42"}]}
    monkeypatch.setattr(McpClient, "call_tool", fake_call)
    await _mcp(env, ["lookup"])
    run, status, _, _ = await run_graph(env, seq("tool-user", tools=["mcp:crm/lookup"]))
    assert status == "completed" and seen and seen[0][0] == "lookup"
    async with dbs.sessionmaker()() as s:
        tr = (await s.execute(select(ToolRun).where(ToolRun.run_id == run.id))).scalar_one()
    assert tr.success and tr.tool == "mcp:crm/lookup"


async def test_mcp_allowlist_and_policy_are_enforced(env, monkeypatch):
    from isocline.services.mcp import McpClient
    called = []

    async def fake_call(self, name, args):
        called.append(name)
        return {}
    monkeypatch.setattr(McpClient, "call_tool", fake_call)
    from isocline.core.errors import AppError
    with pytest.raises(AppError) as e:  # unregistered server: blocked before the run
        await run_graph(env, seq("tool-user", tools=["mcp:crm/lookup"]))
    assert "mcp_server_missing" in str(e.value.detail)
    await _mcp(env, [])  # registered, nothing allowlisted: still blocked, and the model is never offered the tool
    with pytest.raises(AppError) as e:
        await run_graph(env, seq("tool-user", tools=["mcp:crm/lookup"]))
    assert "mcp_tool_not_allowed" in str(e.value.detail) and called == []
    async with dbs.sessionmaker()() as s:
        srv = (await s.execute(select(McpServer))).scalar_one()
        srv.allowed_tools = ["lookup"]
        await s.commit()
    await add_policy(env, [{"kind": "tool", "subject": "mcp:crm/*", "action": "*", "effect": "deny"}])
    run2, _, _, _ = await run_graph(env, seq("tool-user", tools=["mcp:crm/lookup"]))
    async with dbs.sessionmaker()() as s:
        tr2 = (await s.execute(select(ToolRun).where(ToolRun.run_id == run2.id))).scalar_one()
    assert not tr2.success and "Denied by policy" in tr2.error and called == []


# ------------------------------------------------------------------ Goal Mode enforcement & replanning
def test_goal_harness_strips_disallowed_tools_and_rejects_oversized_plans():
    from isocline.schemas.workflow import GoalConfig
    from isocline.services.goal import enforce
    g = GoalConfig(goal="x", agents=["research"], tools=["web_search"], planner_model={"provider": "local_test", "model": "echo"},
                   agent_model={"provider": "local_test", "model": "echo"}, max_agent_calls=2, max_planning_depth=3, max_replans=0)
    plan = {"nodes": [{"key": "a", "type": "agent", "template": "research", "tools": ["web_search", "python", "http_request"]}]}
    out, errors, notes = enforce(g, plan, [])
    assert out["nodes"][0]["tools"] == ["web_search"] and not errors and len(notes) == 2
    big = {"nodes": [{"key": f"a{i}", "type": "agent", "template": "research", "tools": []} for i in range(6)]
           + [{"key": "w", "type": "agent", "template": "developer"}, {"key": "l", "type": "loop"}]}
    _, errors, _ = enforce(g, big, [])
    joined = " ".join(errors)
    assert "limit" in joined and "at most 2 agent calls" in joined and "developer" in joined and "loop" in joined
    pol = [{"policy_name": "p", "scope_type": "workspace", "kind": "tool", "subject": "web_search", "action": "*", "effect": "deny",
            "condition": {}, "value": None, "mandatory": True, "rank": 0}]
    out, _, notes = enforce(g, {"nodes": [{"key": "a", "type": "agent", "template": "research", "tools": ["web_search"]}]}, pol)
    assert out["nodes"][0]["tools"] == [] and "denied" in " ".join(notes).lower()


async def test_goal_mode_replans_when_output_contract_fails(env):
    g = {"schema_version": "2.0", "nodes": [], "edges": [], "settings": {"mode": "goal", "max_llm_calls": 40, "goal": {
        "goal": "Research a company and write a report", "agents": ["research", "manager"], "tools": [],
        "planner_model": {"provider": "local_test", "model": "echo"}, "agent_model": {"provider": "local_test", "model": "bad-json"},
        "output_schema": {"score": "number"}, "max_agent_calls": 6, "max_planning_depth": 8, "max_replans": 1}}}
    run, status, bus, _ = await run_graph(env, g, {})
    async with dbs.sessionmaker()() as s:
        plans = (await s.execute(select(GoalPlan).where(GoalPlan.run_id == run.id).order_by(GoalPlan.version))).scalars().all()
    assert [p.version for p in plans] == [1, 2] and "failed" in plans[1].reason
    assert any(e["type"] == "PLAN_REVISED" for e in bus.events[str(run.id)])
    assert status == "failed"  # bounded: max_replans reached, the harness does not loop


# ------------------------------------------------------------------ approval timeouts, rejected tool approvals
async def test_approval_timeout_takes_timeout_branch(env):
    from isocline.services.waits import process_due_waits
    g = graph([node("inp", "input_text", field="topic"), node("ok", "human_approval", title="Approve", max_wait_seconds=1, timeout_action="edge"),
               node("yes", "output_text", template="approved"), node("late", "output_text", template="expired")],
              [edge("inp", "ok"), edge("ok", "yes", "approved"), edge("ok", "late", "timeout")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    await asyncio.sleep(1.1)
    await process_due_waits(env["db"])
    assert await execute(run.id) == "completed"
    nrs = await node_runs(run.id)
    assert nrs["late"].status == "completed" and nrs["yes"].status == "skipped"
    async with dbs.sessionmaker()() as s:
        a = (await s.execute(select(Approval).where(Approval.run_id == run.id))).scalar_one()
    assert a.status == "expired"


async def test_rejected_tool_approval_never_executes_the_tool(env):
    await add_policy(env, [{"kind": "tool", "subject": "calculator", "action": "*", "effect": "require_approval"}])
    run, status, _, _ = await run_graph(env, seq("tool-user", tools=["calculator"]))
    assert status == "waiting"
    await decide(env, run.id, "rejected", kind="tool_call")
    assert await execute(run.id) == "completed"
    async with dbs.sessionmaker()() as s:
        trs = (await s.execute(select(ToolRun).where(ToolRun.run_id == run.id))).scalars().all()
    assert all(not t.success for t in trs) and any("rejected" in (t.error or "").lower() for t in trs)



# ------------------------------------------------------------------ artifacts consumed by agents; file triggers
async def _document(env, text=b"quarter,revenue\nQ1,10\nQ2,12\n", name="q.csv"):
    from isocline.services.storage import storage
    key = await storage().put(text, ".csv")
    d = Document(project_id=env["project"].id, filename=name, mime="text/csv", size_bytes=len(text), storage_key=key, status="ready")
    env["db"].add(d)
    await env["db"].commit()
    return d


async def test_file_input_as_artifact_records_consumers(env):
    d = await _document(env)
    g = graph([node("file", "input_file", field="file", as_artifact=True), agent("research", prompt="Analyze the file"), node("out", "output_text")],
              [edge("file", "research"), edge("research", "out")])
    run, status, _, _ = await run_graph(env, g, {"file": str(d.id)})
    assert status == "completed"
    ref = (await node_runs(run.id))["file"].output
    assert ref["type"] == "csv" and "storage_key" not in ref
    async with dbs.sessionmaker()() as s:
        use = (await s.execute(select(ArtifactUsage).where(ArtifactUsage.run_id == run.id))).scalars().all()
    assert [u.node_key for u in use] == ["research"]


async def test_file_upload_trigger_starts_published_workflow(env):
    from isocline.services.triggers import fire_file_triggers
    wf = await make_workflow(env, seq())
    env["db"].add(WorkflowVersion(workflow_id=wf.id, version=1, graph=wf.graph))
    env["db"].add(Trigger(project_id=env["project"].id, workflow_id=wf.id, kind="file", name="csv", enabled=True, config={"extensions": [".csv"]}))
    await env["db"].commit()
    d = await _document(env)
    runs = await fire_file_triggers(env["db"], d)
    assert len(runs) == 1
    r = await reload_run(env, uuid.UUID(runs[0]))
    assert r.trigger == "file" and r.input["filename"] == "q.csv"
    pdf = await _document(env, b"%PDF", "x.pdf")
    assert await fire_file_triggers(env["db"], pdf) == []  # extension filter


# ------------------------------------------------------------------ sub-workflow failure and nesting
async def test_subworkflow_failure_follows_parent_failure_policy(env):
    child_g = seq("fail", retry={"retries": 0})
    child = await make_workflow(env, child_g, name="Failing child")
    env["db"].add(WorkflowVersion(workflow_id=child.id, version=1, graph=child_g))
    await env["db"].commit()
    g = graph([node("inp", "input_text", field="topic"), node("team", "subworkflow", workflow_id=str(child.id), version=1, on_failure="continue"),
               node("out", "output_text", template="parent finished")], [edge("inp", "team"), edge("team", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    assert await execute(env["db"].info["queued"][-1]) == "failed"
    assert await execute(run.id) == "completed"
    assert (await node_runs(run.id))["team"].error["kind"] == "subworkflow_failed"


async def test_subworkflow_must_reference_a_published_version(env):
    child = await make_workflow(env, seq(), name="Unpublished")
    g = graph([node("inp", "input_text", field="topic"), node("team", "subworkflow", workflow_id=str(child.id)), node("out", "output_text")],
              [edge("inp", "team"), edge("team", "out")])
    from isocline.core.errors import AppError
    with pytest.raises(AppError) as e:  # caught by preflight before anything runs
        await run_graph(env, g)
    assert "published version" in str(e.value.detail)


# ------------------------------------------------------------------ optimizer cost rules
async def test_optimizer_finds_cheaper_model_and_cache_opportunities(env):
    from isocline.db.seed import seed
    from isocline.services.optimizer import analyze
    await seed(env["db"])
    pr = (await env["db"].execute(select(ModelPricing).where(ModelPricing.provider == "local_test", ModelPricing.model == "echo"))).scalar_one()
    pr.input_per_mtok, pr.output_per_mtok = 50.0, 150.0  # make the test model "expensive"
    await env["db"].commit()
    g = seq()
    for _ in range(3):
        await run_graph(env, g, {"topic": "same input"})
    wf = (await env["db"].execute(select(Run.workflow_id).order_by(Run.created_at.desc()).limit(1))).scalar_one()
    from isocline.db.models import Workflow
    w = await env["db"].get(Workflow, wf)
    opt = await analyze(env["db"], w)
    from isocline.db.models_v2 import OptimizationRecommendation
    recs = (await env["db"].execute(select(OptimizationRecommendation).where(OptimizationRecommendation.optimization_run_id == opt.id))).scalars().all()
    kinds = {r.kind for r in recs}
    assert "cheaper_model" in kinds
    cheap = next(r for r in recs if r.kind == "cheaper_model")
    assert cheap.impact["quality"] == "unknown until evaluated" and cheap.impact["cost_per_run"] < 0


# ------------------------------------------------------------------ fair scheduling
async def test_concurrent_run_quota_defers_queued_runs(env):
    from isocline.db.models_v2 import WorkspaceQuota
    from isocline.services.quotas import should_defer
    db = env["db"]
    db.add(WorkspaceQuota(workspace_id=env["workspace"].id, max_concurrent_runs=1))
    wf = await make_workflow(env, seq())

    def mk(status, hb):
        return Run(workspace_id=env["workspace"].id, project_id=env["project"].id, workflow_id=wf.id, graph_snapshot=wf.graph, settings={},
                   input={}, trigger="ui", status=status, heartbeat_at=hb)
    busy, queued = mk("running", utcnow()), mk("queued", None)
    db.add_all([busy, queued])
    await db.commit()
    assert await should_defer(db, queued) is True  # workspace at its quota: wait without holding a worker
    busy.heartbeat_at = utcnow() - timedelta(minutes=10)  # a dead worker does not count
    await db.commit()
    assert await should_defer(db, queued) is False
    assert await should_defer(db, busy) is False  # only queued runs are ever deferred
