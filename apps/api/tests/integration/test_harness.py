"""V2 harness behaviour, end-to-end through create_run → Executor → SQL store (local_test provider)."""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from isocline.db import session as dbs
from isocline.db.models import Approval, Run, ToolRun
from isocline.db.models_v2 import (
    Artifact, Checkpoint, CompensationAction, GoalPlan, ModelRoutingDecision, Policy, PolicyDecision, PolicyRule,
)
from isocline.engine.events import MemoryBus
from isocline.engine.executor import Executor, callback_token
from isocline.engine.store import SqlRunStore
from tests.conftest import agent, edge, graph, make_workflow, node, node_runs, reload_run, run_graph


def seq(model="echo", **harness_or_cfg):
    harness = harness_or_cfg.pop("harness", None)
    contract = harness_or_cfg.pop("contract", None)
    a = agent("research", model, **harness_or_cfg)
    if harness:
        a["harness"] = harness
    if contract:
        a["contract"] = contract
    return graph([node("inp", "input_text", field="topic"), a, node("out", "output_text")],
                 [edge("inp", "research"), edge("research", "out")])


async def execute(run_id):
    return await Executor(SqlRunStore(MemoryBus()), str(run_id)).execute()


async def add_policy(env, rules, scope="workspace"):
    db = env["db"]
    scope_id = {"workspace": env["workspace"].id, "project": env["project"].id}[scope]
    p = Policy(workspace_id=env["workspace"].id, scope_type=scope, scope_id=scope_id, name=f"{scope} policy")
    db.add(p)
    await db.flush()
    for i, r in enumerate(rules):
        db.add(PolicyRule(policy_id=p.id, position=i, **r))
    await db.commit()


async def decide(env, run_id, status="approved", kind=None):
    from isocline.services.runs import decide_approval
    db = env["db"]
    q = select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
    if kind:
        q = q.where(Approval.kind == kind)
    a = (await db.execute(q)).scalars().first()
    assert a is not None, "expected a pending approval"
    r = await db.get(Run, run_id)
    await db.refresh(r)
    await decide_approval(db, r, a, decision=status, user_id=env["user"].id)
    return a


# ------------------------------------------------------------------ contracts & types
async def test_type_mismatch_blocks_with_suggestion(env):
    from isocline.core.errors import AppError
    g = seq()
    g["nodes"].insert(2, {**agent("calc_agent"), "contract": {"inputs": [{"name": "value", "type": "Number"}]}})
    g["edges"] = [edge("inp", "research"), edge("research", "calc_agent"), edge("calc_agent", "out")]
    with pytest.raises(AppError) as e:
        await run_graph(env, g)
    errs = e.value.detail["details"]
    mism = [x for x in errs if x["code"] == "type_mismatch"]
    assert mism and mism[0]["data"]["suggestion"]["transform"] == "json_parse"


async def test_runtime_output_contract_enforced(env):
    run, status, _, _ = await run_graph(env, seq(contract={"output": {"name": "out", "type": "Number"}}))
    r = await reload_run(env, run.id)
    assert status == "failed" and "Output contract violated" in r.error["message"]


async def test_custom_type_contract_drives_structured_output(env):
    from isocline.db.models_v2 import CustomType
    env["db"].add(CustomType(workspace_id=env["workspace"].id, name="RiskReport", json_schema={"risk_score": "number", "summary": "string"}))
    await env["db"].commit()
    run, status, _, _ = await run_graph(env, seq("json", contract={"output": {"name": "out", "type": "JSON<RiskReport>"}}))
    assert status == "completed"
    out = (await reload_run(env, run.id)).output["result"]
    assert isinstance(out["risk_score"], float)


# ------------------------------------------------------------------ cache
async def test_exact_cache_hit_and_savings(env):
    g = seq(harness={"cache": {"mode": "exact", "ttl_seconds": 3600}})
    r1, s1, _, _ = await run_graph(env, g)
    r2, s2, bus2, _ = await run_graph(env, g)
    assert s1 == s2 == "completed"
    n1, n2 = (await node_runs(r1.id))["research"], (await node_runs(r2.id))["research"]
    assert n1.cache_status == "stored" and n2.cache_status == "hit" and n2.llm_calls == 0
    assert n2.output == n1.output
    assert any(e["type"] == "NODE_CACHE_HIT" for e in bus2.events[str(r2.id)])
    r3, _, _, _ = await run_graph(env, g, {"topic": "something else"})
    assert (await node_runs(r3.id))["research"].cache_status == "stored"


async def test_cache_never_applies_to_side_effects(env):
    g = seq(harness={"cache": {"mode": "exact"}}, tools=["http_request"])
    run, status, bus, _ = await run_graph(env, g)
    assert (await node_runs(run.id))["research"].cache_status == "bypass"
    assert any(e["type"] == "CACHE_BYPASS" and "side-effecting" in e["data"]["reason"] for e in bus.events[str(run.id)])


async def test_semantic_cache_is_scoped_by_signature(env):
    g = seq(harness={"cache": {"mode": "semantic", "similarity_threshold": 0.8}})
    await run_graph(env, g, {"topic": "quarterly revenue of acme corporation"})
    r2, _, _, _ = await run_graph(env, g, {"topic": "quarterly revenue of acme corporation!"})
    assert (await node_runs(r2.id))["research"].cache_status == "hit"
    g2 = seq(harness={"cache": {"mode": "semantic", "similarity_threshold": 0.8}}, prompt="A different prompt: {{input.topic}}")
    r3, _, _, _ = await run_graph(env, g2, {"topic": "quarterly revenue of acme corporation!"})
    assert (await node_runs(r3.id))["research"].cache_status == "stored"  # different signature → no reuse


# ------------------------------------------------------------------ policy engine at runtime
async def test_policy_denies_tool_call_and_logs(env):
    await add_policy(env, [{"kind": "tool", "subject": "calculator", "action": "*", "effect": "deny", "mandatory": True}])
    run, status, bus, _ = await run_graph(env, seq("tool-user", tools=["calculator"]))
    assert status == "completed"  # the agent was told the tool is denied and answered anyway
    async with dbs.sessionmaker()() as s:
        tr = (await s.execute(select(ToolRun).where(ToolRun.run_id == run.id))).scalar_one()
        pd = (await s.execute(select(PolicyDecision).where(PolicyDecision.run_id == run.id))).scalar_one()
    assert not tr.success and "Denied by policy" in tr.error and pd.effect == "deny"


async def test_policy_requires_approval_then_resumes(env):
    await add_policy(env, [{"kind": "tool", "subject": "calculator", "action": "*", "effect": "require_approval"}])
    run, status, _, _ = await run_graph(env, seq("tool-user", tools=["calculator"]))
    assert status == "waiting"
    await decide(env, run.id, "approved", kind="tool_call")
    assert await execute(run.id) == "completed"
    async with dbs.sessionmaker()() as s:
        tr = (await s.execute(select(ToolRun).where(ToolRun.run_id == run.id, ToolRun.success == True))).scalars().all()  # noqa: E712
    assert len(tr) == 1 and tr[0].output["result"] == 22


async def test_run_level_approval_policy(env):
    await add_policy(env, [{"kind": "approval", "subject": "run", "effect": "require_approval",
                            "condition": {"metric": "projected_llm_calls", "op": "gt", "value": 0}}], scope="project")
    run, status, _, _ = await run_graph(env, seq())
    assert status == "waiting" and (await reload_run(env, run.id)).llm_calls == 0  # nothing spent before approval
    await decide(env, run.id, "approved", kind="run_budget")
    assert await execute(run.id) == "completed"


async def test_budget_policy_clamps_limits(env):
    await add_policy(env, [{"kind": "budget", "subject": "max_llm_calls", "effect": "limit", "value": 1}])
    from isocline.core.errors import AppError
    g = graph([node("inp", "input_text", field="topic"), agent("a"), agent("b"), node("out", "output_text")],
              [edge("inp", "a"), edge("a", "b"), edge("b", "out")])
    with pytest.raises(AppError):  # preflight: 2 calls needed, policy allows 1
        await run_graph(env, g)


async def test_model_allowlist_blocks_preflight(env):
    await add_policy(env, [{"kind": "model_allowlist", "subject": "*", "effect": "allow", "value": ["openai/*"], "mandatory": True}])
    from isocline.core.errors import AppError
    with pytest.raises(AppError) as e:
        await run_graph(env, seq())
    assert "approved model list" in str(e.value.detail)


# ------------------------------------------------------------------ AUTO routing
async def test_auto_model_routes_by_capability_and_records_decision(env):
    from isocline.db.seed import seed
    await seed(env["db"])
    g = seq(output_schema={"score": "number"}, routing={"objective": "balanced", "allowed_providers": ["local_test"]})
    g["nodes"][1]["config"]["model"] = {"provider": "auto", "model": "auto"}
    run, status, bus, _ = await run_graph(env, g)
    assert status == "completed", ((await reload_run(env, run.id)).error, [e for e in bus.events[str(run.id)] if e["type"] in ("NODE_ROUTED", "NODE_FAILED")])
    nr = (await node_runs(run.id))["research"]
    assert nr.model == "json"  # the only local_test model registered with structured_output
    async with dbs.sessionmaker()() as s:
        d = (await s.execute(select(ModelRoutingDecision).where(ModelRoutingDecision.run_id == run.id))).scalar_one()
    assert d.selected_model == "json" and any("Structured output" in r for r in d.reasons)
    assert any(c.get("rejected") for c in d.candidates)


# ------------------------------------------------------------------ recovery, SLA, checkpoints
async def test_recovery_escalates_to_human_and_reject_fails(env):
    g = seq("fail", harness={"recovery": [{"attempts_gte": 2, "actions": ["human"]}, {"when": ["any"], "actions": ["retry"]}]},
            retry={"retries": 0, "backoff": "none"})
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    await decide(env, run.id, "rejected", kind="recovery")
    assert await execute(run.id) == "failed"
    assert "chose not to retry" in (await reload_run(env, run.id)).error["message"]


async def test_recovery_fallback_switches_model(env):
    g = seq("fail", fallbacks=[], harness={"recovery": [{"when": ["unavailable"], "actions": ["fallback"]}]})
    g["nodes"][1]["config"]["fallbacks"] = []
    # recovery-driven fallback uses the node's fallback list; give it one that works
    g["nodes"][1]["config"]["fallbacks"] = [{"provider": "local_test", "model": "echo"}]
    run, status, _, _ = await run_graph(env, g)
    assert status == "completed" and (await node_runs(run.id))["research"].model == "echo"


async def test_sla_latency_breach(env):
    g = seq("slow-2", harness={"sla": {"max_latency_ms": 300, "on_breach": "fail"}}, on_failure="continue")
    import time
    t0 = time.monotonic()
    run, status, bus, _ = await run_graph(env, g)
    assert time.monotonic() - t0 < 2.0
    nr = (await node_runs(run.id))["research"]
    assert nr.status == "failed" and nr.error["kind"] == "sla_latency"


async def test_checkpoints_and_resume(env):
    from isocline.services.runs import resume_from_checkpoint
    g = graph([node("inp", "input_text", field="topic"), agent("research"), agent("writer", "fail", retry={"retries": 0}),
               node("out", "output_text")], [edge("inp", "research"), edge("research", "writer"), edge("writer", "out")])
    run, status, _, wf = await run_graph(env, g)
    assert status == "failed"
    async with dbs.sessionmaker()() as s:
        cps = (await s.execute(select(Checkpoint).where(Checkpoint.run_id == run.id))).scalars().all()
    cp = next(c for c in cps if c.node_key == "research")
    db = env["db"]
    parent = await db.get(Run, run.id)
    await db.refresh(parent)
    child = await resume_from_checkpoint(db, parent, cp.id, workflow=wf, project=env["project"])
    assert await execute(child.id) == "failed"  # writer still fails, but research was not re-run
    nrs = await node_runs(child.id)
    assert nrs["research"].llm_calls == 0 and nrs["research"].attempts[0]["status"] == "reused"
    c = await reload_run(env, child.id)
    assert c.parent_run_id == run.id and c.checkpoint_id == cp.id


# ------------------------------------------------------------------ durable waits
async def test_timer_wait_resumes_without_holding_a_worker(env):
    from isocline.services.waits import process_due_waits
    g = graph([node("inp", "input_text", field="topic"), node("pause", "wait_timer", duration_seconds=1), node("out", "output_text")],
              [edge("inp", "pause"), edge("pause", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    await asyncio.sleep(1.1)
    res = await process_due_waits(env["db"])
    assert res["runs_resumed"] == 1 and env["db"].info["queued"][-1] == str(run.id)
    assert await execute(run.id) == "completed"


async def test_webhook_callback_resumes_with_payload(env):
    from isocline.services.waits import resolve_callback, verify_callback
    g = graph([node("inp", "input_text", field="topic"), node("job", "wait_webhook"), node("out", "output_json")],
              [edge("inp", "job"), edge("job", "out")])
    run, status, bus, _ = await run_graph(env, g)
    assert status == "waiting"
    nid = next(n["id"] for n in g["nodes"] if n["key"] == "job")
    assert verify_callback(str(run.id), nid, callback_token(str(run.id), nid))
    assert not verify_callback(str(run.id), nid, "forged")
    assert await resolve_callback(env["db"], str(run.id), nid, {"result": 42}) == "resumed"
    assert await resolve_callback(env["db"], str(run.id), nid, {"result": 43}) == "duplicate"
    assert await execute(run.id) == "completed"
    assert (await reload_run(env, run.id)).output["result"] == {"result": 42}


async def test_event_wait_timeout_takes_timeout_edge(env):
    from isocline.services.waits import process_due_waits, publish_event
    g = graph([node("inp", "input_text", field="topic"), node("ev", "wait_event", event_name="order.paid", correlation="{{input.topic}}", max_wait_seconds=1),
               node("paid", "output_text", template="paid"), node("late", "output_text", template="timed out")],
              [edge("inp", "ev"), edge("ev", "paid"), edge("ev", "late", "timeout")])
    run, status, _, _ = await run_graph(env, g, {"topic": "order-1"})
    assert status == "waiting"
    assert (await publish_event(env["db"], env["workspace"].id, "order.paid", "order-2", {}))["waits_resumed"] == 0  # other order
    await asyncio.sleep(1.1)
    await process_due_waits(env["db"])
    assert await execute(run.id) == "completed"
    nrs = await node_runs(run.id)
    assert nrs["late"].status == "completed" and nrs["paid"].status == "skipped"


async def test_event_wait_resumes_on_matching_event(env):
    from isocline.services.waits import publish_event
    g = graph([node("inp", "input_text", field="topic"), node("ev", "wait_event", event_name="order.paid", correlation="{{input.topic}}"),
               node("out", "output_json")], [edge("inp", "ev"), edge("ev", "out")])
    run, status, _, _ = await run_graph(env, g, {"topic": "order-7"})
    assert (await publish_event(env["db"], env["workspace"].id, "order.paid", "order-7", {"amount": 5}))["runs_resumed"] == 1
    assert await execute(run.id) == "completed"
    assert (await reload_run(env, run.id)).output["result"]["payload"] == {"amount": 5}


# ------------------------------------------------------------------ sub-workflows
async def test_subworkflow_runs_as_child_and_rolls_up_cost(env):
    from isocline.db.models import WorkflowVersion
    child_g = seq()
    child = await make_workflow(env, child_g, name="Child")
    env["db"].add(WorkflowVersion(workflow_id=child.id, version=1, graph=child_g))
    child.latest_version = 1
    await env["db"].commit()
    g = graph([node("inp", "input_text", field="topic"),
               node("team", "subworkflow", workflow_id=str(child.id), version=1, input_mapping={"topic": "{{input.topic}}"}),
               node("out", "output_text")], [edge("inp", "team"), edge("team", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    child_run_id = env["db"].info["queued"][-1]
    assert await execute(child_run_id) == "completed"
    assert env["db"].info["queued"][-1] == str(run.id)  # parent re-queued by the child
    assert await execute(run.id) == "completed"
    p = await reload_run(env, run.id)
    assert "acme" in p.output["result"] and p.llm_calls == 1  # child's call rolled up


# ------------------------------------------------------------------ compensation & artifacts
async def test_compensation_is_recorded_and_policy_gated(env):
    from isocline.services.compensation import run_compensations
    await add_policy(env, [{"kind": "tool", "subject": "http_request", "action": "write", "effect": "deny"}])
    calc = node("create", "tool_calculator", arguments={"expression": "2+2"})
    calc["harness"] = {"compensation": {"tool": "http_request", "arguments": {"method": "DELETE", "url": "https://example.com/items/{{this.output.result}}"}}}
    g = graph([node("inp", "input_text", field="topic"), calc, node("out", "output_text")], [edge("inp", "create"), edge("create", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "completed"
    async with dbs.sessionmaker()() as s:
        ca = (await s.execute(select(CompensationAction).where(CompensationAction.run_id == run.id))).scalar_one()
    assert ca.compensation["arguments"]["url"].endswith("/items/4") and ca.status == "available"
    res = await run_compensations(str(run.id), actor="policy")
    assert res["skipped"] == 1


async def test_file_output_becomes_artifact_and_csv_to_table(env):
    g = graph([node("inp", "input_text", field="csv"),
               node("table", "transform", mode="csv_to_table", path="{{input.csv}}"),
               node("out", "output_file", template="{{table.output}}", format="file", filename="rows.json")],
              [edge("inp", "table"), edge("table", "out")])
    run, status, _, _ = await run_graph(env, g, {"csv": "month,revenue\nJan,100\nFeb,120"})
    assert status == "completed"
    nrs = await node_runs(run.id)
    assert nrs["table"].output == [{"month": "Jan", "revenue": 100}, {"month": "Feb", "revenue": 120}]
    ref = (await reload_run(env, run.id)).output["result"]["artifact"]
    assert ref["storage_uri"] == "internal" and "storage_key" not in ref
    async with dbs.sessionmaker()() as s:
        a = await s.get(Artifact, uuid.UUID(ref["artifact_id"]))
    assert a.node_key == "out" and a.run_id == run.id and a.size_bytes > 0


# ------------------------------------------------------------------ context engineering
async def test_context_budget_reduces_low_priority_sources_and_traces(env):
    big = "lorem ipsum " * 3000
    g = graph([node("inp", "input_text", field="topic"), agent("research", prompt="Summarize"),
               agent("writer", prompt="Write a short summary",
                     context={"max_context_tokens": 1500, "sources": {"upstream": {"strategy": "truncate"}}}), node("out", "output_text")],
              [edge("inp", "research"), edge("research", "writer"), edge("writer", "out")])
    run, status, _, _ = await run_graph(env, g, {"topic": big})
    assert status == "completed"
    trace = (await node_runs(run.id))["writer"].input["context_trace"]
    assert sum(t["tokens_after"] for t in trace) <= 1500 + 50
    assert any(t["action"] != "kept" for t in trace)
    assert next(t for t in trace if t["category"] == "system")["action"] == "kept"


# ------------------------------------------------------------------ goal mode
async def test_goal_mode_plans_within_bounds_and_persists_plan(env):
    g = {"schema_version": "2.0", "nodes": [], "edges": [], "settings": {"mode": "goal", "goal": {
        "goal": "Research a company, then a financial analyst and a risk analyst in parallel, then a manager writes the final report",
        "agents": ["research", "financial_analyst", "critic", "manager"], "tools": [],
        "planner_model": {"provider": "local_test", "model": "echo"}, "agent_model": {"provider": "local_test", "model": "echo"},
        "max_agent_calls": 6, "max_planning_depth": 8, "max_replans": 0}}}
    run, status, bus, _ = await run_graph(env, g, {})
    assert status == "completed", (await reload_run(env, run.id)).error
    async with dbs.sessionmaker()() as s:
        plans = (await s.execute(select(GoalPlan).where(GoalPlan.run_id == run.id))).scalars().all()
    assert len(plans) == 1 and plans[0].method == "heuristic"
    keys = {n["key"] for n in plans[0].graph["nodes"]}
    assert {"research", "financial", "risk", "manager"} <= keys
    assert any(e["type"] == "PLAN_CREATED" for e in bus.events[str(run.id)])
    r = await reload_run(env, run.id)
    assert r.graph_snapshot["nodes"]  # the executed plan is the run's graph


async def test_sweeper_requeues_lost_queue_without_counting_attempts(env, monkeypatch):
    """Redis restart: queued/resuming runs are re-enqueued from PostgreSQL; only dead RUNNING workers count as attempts."""
    from datetime import timedelta
    from isocline.db.models import utcnow
    from isocline.worker import tasks
    run, status, _, _ = await run_graph(env, seq())
    enq = []
    import isocline.services.dispatch as dispatch
    monkeypatch.setattr(dispatch, "enqueue_run", lambda rid: enq.append(rid))
    async with dbs.sessionmaker()() as s:
        r = await s.get(Run, run.id)
        r.status, r.heartbeat_at, r.created_at = "resuming", utcnow() - timedelta(hours=5), utcnow() - timedelta(hours=5)
        await s.commit()
    monkeypatch.setattr(tasks, "_run", lambda coro: coro)  # await the coroutine here instead of a new event loop
    await tasks.sweep_stale_runs()
    r = await reload_run(env, run.id)
    assert enq == [str(run.id)] and r.recovery_attempts == 0 and r.status == "resuming"
