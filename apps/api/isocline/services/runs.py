"""Run creation, replay lineage, cancellation and approvals."""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError, bad_request, conflict, not_found
from isocline.db.models import Agent, Approval, NodeRun, Project, Run, Workflow, WorkflowVersion, utcnow
from isocline.engine.budget import effective_settings
from isocline.engine.graph import compile_graph

from .dispatch import enqueue_run
from .validation import validate_all


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v not in (None, "", [], {}):
            out[k] = v
    return out


async def resolve_library_agents(db: AsyncSession, graph: dict, workspace_id) -> dict:
    """Snapshots agent configuration into the graph so runs are reproducible:
    library_agent_id → the library agent's current configuration."""
    g = copy.deepcopy(graph)
    for n in g.get("nodes", []):
        lib = (n.get("config") or {}).get("library_agent_id")
        if n.get("type") == "agent" and lib:
            try:
                a = await db.get(Agent, uuid.UUID(str(lib)))
            except ValueError:
                a = None
            if a is None or a.workspace_id != workspace_id:
                raise bad_request(f"Library agent for node '{n.get('key')}' was not found")
            n["config"] = _deep_merge(a.config, n["config"])
    return g


async def create_run(db: AsyncSession, *, workflow: Workflow, project: Project, run_input: dict, user_id=None,
                     trigger: str = "ui", version: WorkflowVersion | None = None, idempotency_key: str | None = None,
                     graph_override: dict | None = None, dispatch: bool = True,
                     trigger_id=None, skip_plan: bool = False, extra_settings: dict | None = None,
                     subject: str | None = None) -> Run:
    """Creates a run with a complete, immutable harness snapshot: graph, clamped limits,
    policy rules, custom types, quotas and the execution plan. Blocked preflights never create a run."""
    from isocline.db.models_v2 import ExecutionPlan
    from isocline.engine.planner import build_plan, graph_hash
    from isocline.engine.policy import apply_budget_clamps, approval_rules_triggered
    from isocline.services.policies import snapshot as policy_snapshot
    from isocline.services.quotas import enforce_monthly, get_quota
    from isocline.services.types_registry import custom_types_for
    if idempotency_key:
        existing = (await db.execute(select(Run).where(Run.workflow_id == workflow.id, Run.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing:
            return existing
    await enforce_monthly(db, project.workspace_id)
    raw = graph_override or (version.graph if version else workflow.graph)
    raw = await resolve_library_agents(db, raw, project.workspace_id)
    graph, issues = await validate_all(db, raw, project.workspace_id, project.id)
    goal_mode = graph is not None and graph.settings.mode == "goal"
    errors = [i for i in issues if i["severity"] == "error" and not (goal_mode and i["code"] in ("empty_workflow", "no_output"))]
    if errors:
        raise AppError(422, "validation_failed", "Cannot run: the workflow has errors", errors)
    policy = await policy_snapshot(db, workspace_id=project.workspace_id, project_id=project.id,
                                   workflow_id=workflow.id)
    settings = apply_budget_clamps(effective_settings(graph.settings), policy)
    quota = await get_quota(db, project.workspace_id)
    settings["max_parallel_nodes"] = min(settings["max_parallel_nodes"], quota.max_concurrent_nodes)
    custom = await custom_types_for(db, project.workspace_id)
    settings.update({"_policy": policy, "_custom_types": custom, "_sandbox_concurrency": quota.sandbox_concurrency,
                     "workflow_memory_enabled": graph.settings.workflow_memory_enabled})
    first_model = next((n.config.get("model") for n in graph.nodes if n.type == "agent"
                        and (n.config.get("model") or {}).get("provider") not in (None, "", "auto")), None)
    if first_model:
        settings["_summarizer"] = first_model
    for k, v in (extra_settings or {}).items():
        if k.startswith("_"):  # server-controlled settings are never taken from users
            settings[k] = v
    snapshot = graph.model_dump(mode="json")
    if goal_mode:
        g = graph.settings.goal
        settings["_goal"] = g.model_dump(mode="json")
        settings["max_llm_calls"] = min(settings["max_llm_calls"], g.max_agent_calls * 3 + g.max_replans + 1)
        snapshot = {**snapshot, "nodes": [], "edges": []}  # planned inside the worker
        if isinstance(run_input, dict):
            run_input = {"goal": g.goal, "request": g.goal, **run_input}
    plan_row = None
    if not skip_plan:
        plan = await build_plan(db, graph, workflow_id=workflow.id, workspace_id=project.workspace_id, project_id=project.id,
                                settings=settings, policy=policy, env_issues=[], custom_types=custom)
        if plan["status"] == "BLOCKED":
            raise AppError(422, "preflight_blocked", "Preflight blocked this run",
                           [{"severity": "error", "code": "preflight", "message": c["message"], **({"node_id": c["node_id"]} if c.get("node_id") else {})}
                            for c in plan["checks"] if c["status"] == "fail"])
        plan_row = ExecutionPlan(workflow_id=workflow.id, graph_hash=graph_hash(snapshot), status=plan["status"], plan=plan)
        db.add(plan_row)
        await db.flush()
        t = plan["totals"]
        fired = approval_rules_triggered(policy, {"projected_cost": t["cost_usd"][1], "projected_tokens": t["tokens"][1],
                                                  "projected_llm_calls": t["llm_calls"][1]})
        if fired and trigger not in ("replay",):
            settings["_run_approval"] = {"reasons": [f"{r['policy_name']}: {r['condition'].get('metric')} {r['condition'].get('op', 'gt')} {r['condition'].get('value')}"
                                                     for r in fired],
                                         "projected": {"cost_usd": t["cost_usd"], "tokens": t["tokens"], "llm_calls": t["llm_calls"]}}
    run = Run(workspace_id=project.workspace_id, project_id=project.id, workflow_id=workflow.id,
              workflow_version_id=version.id if version else None, graph_snapshot=snapshot,
              settings=settings, status="queued", input=run_input or {}, trigger=trigger,
              idempotency_key=idempotency_key, created_by=user_id,
              execution_plan_id=plan_row.id if plan_row else None, trigger_id=trigger_id)
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(select(Run).where(Run.workflow_id == workflow.id, Run.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing:
            return existing
        raise
    if dispatch:
        enqueue_run(str(run.id))
    return run


def downstream_of(graph_raw: dict, node_id: str) -> set[str]:
    from isocline.schemas.workflow import WorkflowGraph
    cg = compile_graph(WorkflowGraph.model_validate(graph_raw))
    seen, stack = set(), [node_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(e.target for e in cg.outgoing.get(n, []))
        # A replayed loop re-runs its whole body
        stack.extend(cg.loop_bodies.get(n, []))
    # If a node inside a loop body is replayed, the owning loop re-runs.
    for loop_id, body in cg.loop_bodies.items():
        if node_id in body:
            seen |= downstream_of(graph_raw, loop_id)
    return seen


async def replay_run(db: AsyncSession, parent: Run, from_node_id: str, *, user_id=None, use_current_draft: bool = False,
                     workflow: Workflow, project: Project) -> Run:
    """Creates a NEW run (lineage) that reuses successful upstream outputs and re-executes from_node and downstream."""
    if parent.status in ("queued", "running", "resuming"):
        raise conflict("Wait for the run to finish before replaying")
    graph_raw = workflow.graph if use_current_draft else parent.graph_snapshot
    node_ids = {n["id"] for n in graph_raw.get("nodes", [])}
    if from_node_id not in node_ids:
        raise not_found("Node")
    rerun = downstream_of(graph_raw, from_node_id)
    child = await create_run(db, workflow=workflow, project=project, run_input=parent.input, user_id=user_id, trigger="replay",
                             graph_override=graph_raw, dispatch=False)
    child.parent_run_id = parent.id
    child.replay_from_node_id = from_node_id
    if not use_current_draft:
        child.workflow_version_id = parent.workflow_version_id
    parent_nodes = (await db.execute(select(NodeRun).where(NodeRun.run_id == parent.id))).scalars().all()
    for nr in parent_nodes:
        if nr.node_id in rerun or nr.status not in ("completed", "skipped"):
            continue
        if nr.node_id not in node_ids:
            continue
        db.add(NodeRun(run_id=child.id, node_id=nr.node_id, node_key=nr.node_key, node_type=nr.node_type, scope=nr.scope,
                       status=nr.status, input=nr.input, config=nr.config, output=nr.output, handle=nr.handle,
                       attempts=[{"status": "reused", "from_run_id": str(parent.id)}], provider=nr.provider, model=nr.model,
                       started_at=nr.started_at, finished_at=nr.finished_at, latency_ms=0))
    await db.commit()
    enqueue_run(str(child.id))
    return child


async def resume_from_checkpoint(db: AsyncSession, parent: Run, checkpoint_id, *, workflow: Workflow, project: Project,
                                 user_id=None) -> Run:
    """New run lineage from a checkpoint: node outputs complete at the checkpoint are reused, everything after re-runs."""
    from isocline.db.models_v2 import Checkpoint
    cp = await db.get(Checkpoint, checkpoint_id)
    if cp is None or cp.run_id != parent.id:
        raise not_found("Checkpoint")
    if parent.status in ("queued", "running", "resuming"):
        raise conflict("Wait for the run to finish before resuming from a checkpoint")
    reuse = set(cp.completed_node_runs or [])
    child = await create_run(db, workflow=workflow, project=project, run_input=parent.input, user_id=user_id, trigger="checkpoint",
                             graph_override=parent.graph_snapshot, dispatch=False, skip_plan=True)
    child.parent_run_id, child.checkpoint_id, child.workflow_version_id = parent.id, cp.id, parent.workflow_version_id
    prior = (await db.execute(select(NodeRun).where(NodeRun.run_id == parent.id))).scalars().all()
    for nr in prior:
        if str(nr.id) in reuse:
            db.add(NodeRun(run_id=child.id, node_id=nr.node_id, node_key=nr.node_key, node_type=nr.node_type, scope=nr.scope,
                           status=nr.status, input=nr.input, config=nr.config, output=nr.output, handle=nr.handle,
                           attempts=[{"status": "reused", "from_run_id": str(parent.id), "checkpoint_id": str(cp.id)}],
                           provider=nr.provider, model=nr.model, started_at=nr.started_at, finished_at=nr.finished_at,
                           latency_ms=nr.latency_ms))
    await db.commit()
    enqueue_run(str(child.id))
    return child


async def cancel_run(db: AsyncSession, run: Run) -> Run:
    if run.status in ("completed", "failed", "cancelled"):
        return run
    if run.status in ("queued", "waiting"):
        run.status = "cancelled"
        run.finished_at = utcnow()
        run.error = {"code": "cancelled", "message": "Run cancelled by user"}
        await db.execute(update(Approval).where(Approval.run_id == run.id, Approval.status == "pending").values(status="cancelled"))
        await db.execute(update(NodeRun).where(NodeRun.run_id == run.id, NodeRun.status.in_(["waiting", "queued"])).values(status="cancelled"))
    run.cancel_requested = True
    await db.commit()
    return run


async def decide_approval(db: AsyncSession, run: Run, approval: Approval, *, decision: str, user_id, edited_content=None,
                          comment: str | None = None) -> Approval:
    if approval.status != "pending":
        raise conflict("This approval has already been decided")
    if decision not in ("approved", "rejected"):
        raise bad_request("decision must be 'approved' or 'rejected'")
    if edited_content is not None and not approval.allow_edit:
        raise bad_request("Editing is not allowed for this approval")
    approval.status = decision
    approval.edited_content = edited_content
    approval.comment = comment
    approval.decided_by = user_id
    approval.decided_at = utcnow()
    # Only resume when nothing else is still pending for this run.
    await db.flush()
    others = (await db.execute(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending"))).scalars().all()
    if run.status == "waiting":
        run.status = "resuming"
        run.heartbeat_at = utcnow()  # the stale-run sweeper measures from the resume, not from before the wait
    await db.commit()
    if run.status == "resuming":
        enqueue_run(str(run.id))
    return approval
