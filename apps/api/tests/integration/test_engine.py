"""End-to-end execution through the real service layer, executor, SQL store and local_test provider."""
import time

import pytest
from sqlalchemy import select

from isocline.db import session as dbs
from isocline.db.models import Approval, Run, ToolRun
from isocline.engine.events import MemoryBus
from isocline.engine.executor import Executor
from isocline.engine.store import SqlRunStore
from tests.conftest import agent, edge, graph, node, node_runs, reload_run, run_graph


def seq_graph(model="echo", **agent_cfg):
    return graph([node("inp", "input_text", field="topic"), agent("research", model, **agent_cfg), node("out", "output_text")],
                 [edge("inp", "research"), edge("research", "out")])


async def test_input_agent_output(env):
    run, status, bus, _ = await run_graph(env, seq_graph())
    assert status == "completed"
    r = await reload_run(env, run.id)
    assert "[local-test]" in r.output["result"] and "acme" in r.output["result"]
    assert r.llm_calls == 1 and r.input_tokens > 0
    types = [e["type"] for e in bus.events[str(run.id)]]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_COMPLETED"
    assert "NODE_STARTED" in types and "NODE_COMPLETED" in types
    nrs = await node_runs(run.id)
    assert nrs["research"].model == "echo" and nrs["research"].latency_ms is not None
    assert "user_message" in nrs["research"].input  # inspector: resolved input


async def test_parallel_nodes_run_concurrently(env):
    g = graph([node("a", "input_text", field="topic"), agent("b", "slow-1"), agent("c", "slow-1"), agent("e", "slow-1"),
               node("d", "merge", strategy="named"), node("out", "output_json")],
              [edge("a", "b"), edge("a", "c"), edge("a", "e"), edge("b", "d"), edge("c", "d"), edge("e", "d"), edge("d", "out")])
    t0 = time.monotonic()
    run, status, _, _ = await run_graph(env, g)
    elapsed = time.monotonic() - t0
    assert status == "completed"
    assert elapsed < 2.5, f"three 1s agents took {elapsed:.2f}s: not concurrent"
    r = await reload_run(env, run.id)
    assert set(r.output["result"].keys()) == {"b", "c", "e"}
    nrs = await node_runs(run.id)
    starts = sorted(nrs[k].started_at for k in "bce")
    assert (starts[-1] - starts[0]).total_seconds() < 0.5


async def test_condition_routes_and_skips(env):
    g = graph([node("inp", "input_json", field="data"),
               node("check", "condition", rule={"left": "{{input.data.risk}}", "operator": ">", "right": 0.8}),
               agent("review", prompt="review"), agent("cont", prompt="continue"),
               node("out1", "output_text"), node("out2", "output_text")],
              [edge("inp", "check"), edge("check", "review", "true"), edge("check", "cont", "false"),
               edge("review", "out1"), edge("cont", "out2")])
    run, status, _, _ = await run_graph(env, g, {"data": {"risk": 0.9}})
    assert status == "completed"
    nrs = await node_runs(run.id)
    assert nrs["review"].status == "completed" and nrs["cont"].status == "skipped" and nrs["out2"].status == "skipped"
    assert nrs["check"].handle == "true"


async def test_router(env):
    g = graph([node("inp", "input_text", field="topic"),
               node("route", "router", routes=[{"name": "code", "left": "{{input.topic}}", "operator": "contains", "right": "python"},
                                                {"name": "finance", "left": "{{input.topic}}", "operator": "contains", "right": "revenue"}]),
               agent("coder", prompt="c"), agent("fin", prompt="f"), agent("gen", prompt="g"),
               node("merge", "merge", strategy="named"), node("out", "output_json")],
              [edge("inp", "route"), edge("route", "coder", "code"), edge("route", "fin", "finance"), edge("route", "gen", "default"),
               edge("coder", "merge"), edge("fin", "merge"), edge("gen", "merge"), edge("merge", "out")])
    run, status, _, _ = await run_graph(env, g, {"topic": "quarterly revenue"})
    assert status == "completed"
    nrs = await node_runs(run.id)
    assert nrs["fin"].status == "completed" and nrs["coder"].status == "skipped" and nrs["gen"].status == "skipped"
    r = await reload_run(env, run.id)
    assert list(r.output["result"].keys()) == ["fin"]


async def test_bounded_loop(env):
    g = graph([node("inp", "input_json", field="items"),
               node("lp", "loop", collection="{{input.items}}", max_iterations=3),
               node("tx", "transform", mode="template", template="item={{loop.item}}"),
               node("out", "output_json")],
              [edge("inp", "lp"), edge("lp", "tx", "body"), edge("lp", "out", "done")], max_loop_iterations=10)
    run, status, _, _ = await run_graph(env, g, {"items": [1, 2, 3, 4, 5]})
    assert status == "completed"
    r = await reload_run(env, run.id)
    res = r.output["result"]
    assert res["count"] == 3 and res["iterations"] == ["item=1", "item=2", "item=3"]
    assert res["stopped_by"] == "max_iterations" and res.get("truncated_to_max_iterations")


async def test_retry_then_fallback_records_actual_model(env):
    g = seq_graph("fail", fallbacks=[{"provider": "local_test", "model": "ratelimit"}, {"provider": "local_test", "model": "echo"}])
    run, status, bus, _ = await run_graph(env, g)
    assert status == "completed"
    nrs = await node_runs(run.id)
    assert nrs["research"].model == "echo" and nrs["research"].fallback_used
    assert any(e["type"] == "NODE_FALLBACK" for e in bus.events[str(run.id)])


async def test_failed_model_call_retries_then_fails_run(env):
    g = seq_graph("fail", retry={"retries": 2, "backoff": "fixed", "base_delay_seconds": 0})
    run, status, bus, _ = await run_graph(env, g)
    assert status == "failed"
    r = await reload_run(env, run.id)
    assert r.error["code"] == "node_failed" and r.error["node_key"] == "research"
    nrs = await node_runs(run.id)
    failed_attempts = [a for a in nrs["research"].attempts if a.get("status") == "failed" and "attempt" in a]
    assert len(failed_attempts) == 3
    assert sum(1 for e in bus.events[str(run.id)] if e["type"] == "NODE_RETRY") == 2


async def test_on_failure_continue_and_route_error(env):
    g = graph([node("inp", "input_text", field="topic"), agent("bad", "fail", on_failure="route_error"),
               node("handler", "transform", mode="template", template="handled: {{bad.output.error}}"),
               node("out", "output_text")],
              [edge("inp", "bad"), edge("bad", "handler", "error"), edge("handler", "out")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "completed"
    r = await reload_run(env, run.id)
    assert r.output["result"].startswith("handled:")


async def test_budget_termination(env):
    g = graph([node("inp", "input_text", field="topic"), agent("a"), agent("b"), agent("c"), node("out", "output_text")],
              [edge("inp", "a"), edge("a", "b"), edge("b", "c"), edge("c", "out")], max_llm_calls=2)
    # V2: preflight blocks a run that cannot fit its budget, before any spend
    from isocline.core.errors import AppError
    with pytest.raises(AppError) as e:
        await run_graph(env, g)
    assert e.value.detail["code"] == "preflight_blocked" and "model calls" in str(e.value.detail["details"])
    # the runtime limit still stops a run if it gets that far (defence in depth)
    run, status, bus, _ = await run_graph(env, g, skip_plan=True)
    assert status == "failed"
    r = await reload_run(env, run.id)
    assert r.error["code"] == "budget_exceeded" and r.error["limit"] == "max_llm_calls"
    assert r.llm_calls == 2


async def test_runtime_limit(env):
    g = seq_graph("slow-2")
    g["settings"]["max_runtime_seconds"] = 1
    run, status, _, _ = await run_graph(env, g)
    r = await reload_run(env, run.id)
    assert status == "failed" and r.error["code"] == "budget_exceeded"


async def test_structured_output_enforced(env):
    schema = {"company": "string", "risk_score": "number"}
    run, status, _, _ = await run_graph(env, seq_graph("json", output_schema=schema))
    assert status == "completed"
    r = await reload_run(env, run.id)
    assert isinstance(r.output["result"]["risk_score"], float)
    # invalid JSON is repaired or fails explicitly — it never propagates silently
    run2, status2, _, _ = await run_graph(env, seq_graph("bad-json", output_schema=schema))
    r2 = await reload_run(env, run2.id)
    assert status2 == "failed" and "structured" in str(r2.error).lower()


async def test_tool_permissions_and_calculator_tool(env):
    run, status, _, _ = await run_graph(env, seq_graph("tool-user", tools=["calculator"]))
    assert status == "completed"
    async with dbs.sessionmaker()() as s:
        trs = (await s.execute(select(ToolRun).where(ToolRun.run_id == run.id))).scalars().all()
    assert len(trs) == 1 and trs[0].tool == "calculator" and trs[0].success and trs[0].output["result"] == 22
    # without the grant, the model is never offered the tool
    run2, status2, _, _ = await run_graph(env, seq_graph("tool-user", tools=[]))
    async with dbs.sessionmaker()() as s:
        assert not (await s.execute(select(ToolRun).where(ToolRun.run_id == run2.id))).scalars().all()


async def test_human_approval_pause_and_resume(env):
    from isocline.services.runs import decide_approval
    g = graph([node("inp", "input_text", field="topic"), agent("rec"),
               node("appr", "human_approval", title="Approve recommendation"),
               agent("mgr", prompt="Finalize: {{appr.content}}"), agent("rev", prompt="revise"),
               node("out", "output_text"), node("out_rej", "output_text")],
              [edge("inp", "rec"), edge("rec", "appr"), edge("appr", "mgr", "approved"), edge("appr", "rev", "rejected"),
               edge("mgr", "out"), edge("rev", "out_rej")])
    run, status, _, _ = await run_graph(env, g)
    assert status == "waiting"
    db = env["db"]
    r = await db.get(Run, run.id)
    await db.refresh(r)
    assert r.status == "waiting"
    ap = (await db.execute(select(Approval).where(Approval.run_id == run.id))).scalar_one()
    await decide_approval(db, r, ap, decision="approved", user_id=env["user"].id, edited_content="EDITED TEXT", comment="ok")
    assert db.info["queued"] == [str(run.id)]
    status = await Executor(SqlRunStore(MemoryBus()), str(run.id)).execute()
    assert status == "completed"
    nrs = await node_runs(run.id)
    assert nrs["rec"].llm_calls == 1  # not re-executed on resume
    assert nrs["mgr"].status == "completed" and nrs["rev"].status == "skipped"
    assert "EDITED TEXT" in nrs["mgr"].input["user_message"]


async def test_cancel_run(env):
    from isocline.services.runs import cancel_run
    import asyncio
    from tests.conftest import make_workflow
    from isocline.services.runs import create_run
    wf = await make_workflow(env, seq_graph("slow-2"))
    run = await create_run(env["db"], workflow=wf, project=env["project"], run_input={"topic": "x"}, dispatch=False)
    task = asyncio.create_task(Executor(SqlRunStore(MemoryBus()), str(run.id)).execute())
    await asyncio.sleep(0.5)
    async with dbs.sessionmaker()() as s:
        await cancel_run(s, await s.get(Run, run.id))
    status = await asyncio.wait_for(task, 10)
    assert status == "cancelled"


async def test_replay_from_node_reuses_upstream(env):
    from isocline.services.runs import replay_run
    g = graph([node("inp", "input_text", field="topic"), agent("research"), agent("writer", prompt="{{research.output}}"),
               node("out", "output_text")], [edge("inp", "research"), edge("research", "writer"), edge("writer", "out")])
    run, status, _, wf = await run_graph(env, g)
    db = env["db"]
    parent = await db.get(Run, run.id)
    await db.refresh(parent)
    child = await replay_run(db, parent, "writer", workflow=wf, project=env["project"])
    assert child.parent_run_id == parent.id
    status = await Executor(SqlRunStore(MemoryBus()), str(child.id)).execute()
    assert status == "completed"
    c = await reload_run(env, child.id)
    assert c.llm_calls == 1  # only writer re-ran
    p = await reload_run(env, parent.id)
    assert p.status == "completed" and p.llm_calls == 2  # history untouched


async def test_idempotency_key(env):
    from isocline.services.runs import create_run
    from tests.conftest import make_workflow
    wf = await make_workflow(env, seq_graph())
    a = await create_run(env["db"], workflow=wf, project=env["project"], run_input={"topic": "x"}, idempotency_key="k1", dispatch=False)
    b = await create_run(env["db"], workflow=wf, project=env["project"], run_input={"topic": "x"}, idempotency_key="k1", dispatch=False)
    assert a.id == b.id


async def test_validation_blocks_run(env):
    from isocline.core.errors import AppError
    from isocline.services.runs import create_run
    from tests.conftest import make_workflow
    g = graph([node("inp", "input_text"), node("a", "agent", prompt="x"), node("out", "output_text")],
              [edge("inp", "a"), edge("a", "out")])
    wf = await make_workflow(env, g)
    with pytest.raises(AppError) as e:
        await create_run(env["db"], workflow=wf, project=env["project"], run_input={}, dispatch=False)
    assert e.value.status_code == 422


async def test_missing_credential_blocks_real_provider(env):
    from isocline.core.errors import AppError
    from isocline.services.runs import create_run
    from tests.conftest import make_workflow
    g = seq_graph()
    g["nodes"][1]["config"]["model"] = {"provider": "openai", "model": "gpt-4o"}
    wf = await make_workflow(env, g)
    with pytest.raises(AppError) as e:
        await create_run(env["db"], workflow=wf, project=env["project"], run_input={}, dispatch=False)
    assert any(d["code"] == "credential_missing" for d in e.value.detail["details"])


async def test_secrets_never_in_events_or_node_records(env):
    from isocline.core.security import encrypt_secret
    from isocline.db.models import ProviderCredential, RunEvent
    db = env["db"]
    db.add(ProviderCredential(workspace_id=env["workspace"].id, provider="custom", name="MY_TOKEN",
                              encrypted_value=encrypt_secret("supersecretvalue123"), hint="e123"))
    await db.commit()
    g = graph([node("inp", "input_text", field="topic"),
               node("calc", "tool_calculator", arguments={"expression": "1+1"}),
               node("out", "output_text", template="done {{calc.output.result}}")],
              [edge("inp", "calc"), edge("calc", "out")])
    run, status, bus, _ = await run_graph(env, g)
    assert status == "completed"
    async with dbs.sessionmaker()() as s:
        evs = (await s.execute(select(RunEvent).where(RunEvent.run_id == run.id))).scalars().all()
    assert "supersecretvalue123" not in str([e.data for e in evs])
