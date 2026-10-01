from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_run, load_workflow, membership, parse_uuid
from isocline.core.errors import AppError, bad_request, not_found
from isocline.db.models import User
from isocline.db.models_v2 import (
    Checkpoint, CompensationAction, CustomType, ExecutionPlan, GoalPlan, ModelRoutingDecision, PolicyDecision, WaitState,
)
from isocline.db.session import get_db
from isocline.services.audit import audit

router = APIRouter(tags=["harness"])


class GraphIn(BaseModel):
    graph: dict | None = None


class ContextPreviewIn(BaseModel):
    graph: dict | None = None
    input: Any = Field(default_factory=dict)
    mocks: dict[str, Any] = Field(default_factory=dict)


class CustomTypeIn(BaseModel):
    name: str = Field(pattern=r"^[A-Z][A-Za-z0-9_]{0,63}$")
    description: str = ""
    json_schema: dict


# ------------------------------------------------------------------ planning & types
@router.post("/workflows/{workflow_id}/plan")
async def plan(workflow_id: str, body: GraphIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Execution plan + preflight (READY/BLOCKED) for the draft (or a supplied graph), """
    from isocline.engine.budget import effective_settings
    from isocline.engine.planner import build_plan
    from isocline.engine.policy import apply_budget_clamps
    from isocline.services.policies import snapshot
    from isocline.services.runs import resolve_library_agents
    from isocline.services.types_registry import custom_types_for
    from isocline.services.validation import parse_graph, validate_environment
    wf, p = await load_workflow(db, user, workflow_id)
    raw = await resolve_library_agents(db, body.graph if body.graph is not None else wf.graph, p.workspace_id)
    graph, issues = parse_graph(raw)
    if graph is None:
        return {"status": "BLOCKED", "checks": [{"category": "Structure", "status": "fail", "message": i.message} for i in issues],
                "totals": None, "nodes": [], "counts": {}}
    policy = await snapshot(db, workspace_id=p.workspace_id, project_id=p.id, workflow_id=wf.id)
    settings = apply_budget_clamps(effective_settings(graph.settings), policy)
    env_issues = [i.as_dict() for i in await validate_environment(db, graph, p.workspace_id, p.id)]
    return await build_plan(db, graph, workflow_id=wf.id, workspace_id=p.workspace_id, project_id=p.id, settings=settings,
                            policy=policy, env_issues=env_issues, custom_types=await custom_types_for(db, p.workspace_id))


@router.post("/workflows/{workflow_id}/edge-types")
async def edge_types(workflow_id: str, body: GraphIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.engine.graph import edge_types as et
    from isocline.services.types_registry import custom_types_for
    from isocline.services.validation import parse_graph
    wf, p = await load_workflow(db, user, workflow_id)
    graph, _ = parse_graph(body.graph if body.graph is not None else wf.graph)
    return {} if graph is None else et(graph, await custom_types_for(db, p.workspace_id))


@router.post("/workflows/{workflow_id}/nodes/{node_id}/context-preview")
async def context_preview(workflow_id: str, node_id: str, body: ContextPreviewIn, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    """What would enter the model, by category, with token estimates and reductions — without calling a model.
    Upstream values: explicit mocks, else the latest completed run's outputs, else a placeholder."""
    from isocline.db.models import NodeRun, Run
    from isocline.engine.agent_runtime import effective_agent_config
    from isocline.engine.context import assemble
    from isocline.engine.expressions import Scope
    from isocline.services.knowledge import retrieve
    from isocline.services.validation import parse_graph
    wf, p = await load_workflow(db, user, workflow_id)
    graph, _ = parse_graph(body.graph if body.graph is not None else wf.graph)
    if graph is None:
        raise bad_request("The workflow graph is invalid")
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if node is None or node.type != "agent":
        raise not_found("Agent node")
    cfg = effective_agent_config(node.config)
    last = (await db.execute(select(Run).where(Run.workflow_id == wf.id, Run.status == "completed").order_by(Run.created_at.desc()).limit(1))).scalar_one_or_none()
    history = {}
    if last:
        history = {nr.node_key: nr.output for nr in (await db.execute(select(NodeRun).where(NodeRun.run_id == last.id, NodeRun.scope == ""))).scalars()}
    keys = {n.id: n.key for n in graph.nodes}
    ups = [keys[e.source] for e in graph.edges if e.target == node_id and e.source in keys]
    upstream = {k: body.mocks.get(k, history.get(k, f"[output of {k} — run the workflow or add a mock to preview real content]")) for k in ups}
    sources = {k: ("mock" if k in body.mocks else "last run" if k in history else "placeholder") for k in ups}
    run_input = body.input or (last.input if last else {})
    outputs = {**history, **body.mocks}
    sc = Scope(run_input, outputs, variables=graph.settings.variables)
    from isocline.db.models import ModelPricing

    class PreviewCtx:
        limits = {"workflow_memory_enabled": graph.settings.workflow_memory_enabled}
        pricing_cache = {}

        async def memory(self):
            from isocline.db.models import WorkflowMemory
            rows = (await db.execute(select(WorkflowMemory).where(WorkflowMemory.workflow_id == wf.id))).scalars().all()
            return {r.key: r.value for r in rows}

        async def retrieve(self, kb_ids, query):
            return await retrieve(db, kb_ids, query)

        async def artifact_text(self, aid, n):
            return ""
    ctx = PreviewCtx()
    pr = (await db.execute(select(ModelPricing).where(ModelPricing.provider == cfg.model.provider, ModelPricing.model == cfg.model.model))).scalar_one_or_none()
    if pr:
        ctx.pricing_cache[(cfg.model.provider, cfg.model.model)] = {"context_window": pr.context_window}
    tool_tokens = 150 * len(cfg.tools)
    if not cfg.context.sources and cfg.context.upstream_keys is None:
        # preview V1-configured agents with the V2 assembler in preview mode (same categories, no side effects)
        pass
    msgs, record = await assemble(cfg, node, sc, upstream, ctx, preview=True, tool_tokens=tool_tokens)
    return {"model": f"{cfg.model.provider}/{cfg.model.model}", "context_window": pr.context_window if pr else None,
            "budget": record.get("context_budget"), "total_tokens": record.get("context_total_tokens"),
            "categories": record.get("context_trace"), "upstream_sources": sources, "over_budget": record.get("context_over_budget"),
            "note": "Estimates (~4 characters per token). Provider-internal reasoning is never part of the context and is not shown."}


@router.get("/workspaces/{workspace_id}/models/capabilities")
async def capabilities(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.model_intel import capability_table
    await membership(db, user, workspace_id)
    return await capability_table(db, parse_uuid(workspace_id))


# ------------------------------------------------------------------ custom types
@router.get("/workspaces/{workspace_id}/types")
async def list_types(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.engine.types import BUILTIN
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(CustomType).where(CustomType.workspace_id == parse_uuid(workspace_id)).order_by(CustomType.name))).scalars().all()
    return {"builtin": sorted(BUILTIN) + ["JSON<T>", "Artifact<kind>"],
            "custom": [dump(t, "id", "name", "description", "json_schema", "created_at") for t in rows]}


@router.post("/workspaces/{workspace_id}/types", status_code=201)
async def create_type(workspace_id: str, body: CustomTypeIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.engine.structured import normalize_schema
    from isocline.engine.types import BUILTIN
    await membership(db, user, workspace_id, "editor")
    if body.name in BUILTIN:
        raise bad_request(f"'{body.name}' is a built-in type")
    try:
        normalize_schema(body.json_schema)
    except Exception as e:
        raise bad_request(f"Invalid schema: {e}") from e
    wid = parse_uuid(workspace_id)
    existing = (await db.execute(select(CustomType).where(CustomType.workspace_id == wid, CustomType.name == body.name))).scalar_one_or_none()
    t = existing or CustomType(workspace_id=wid, name=body.name)
    t.description, t.json_schema = body.description, body.json_schema
    if not existing:
        db.add(t)
    await db.commit()
    return dump(t, "id", "name", "description", "json_schema", "created_at")


@router.delete("/types/{type_id}", status_code=204)
async def delete_type(type_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(CustomType, parse_uuid(type_id, "Type"))
    if t is None:
        raise not_found("Type")
    await membership(db, user, t.workspace_id, "editor")
    await db.delete(t)
    await db.commit()


# ------------------------------------------------------------------ per-run harness records
@router.get("/runs/{run_id}/harness")
async def run_harness(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Everything the harness decided for a run: plan, routing, policy decisions, checkpoints, waits, compensation, goal plans."""
    r = await load_run(db, user, run_id)
    plan = await db.get(ExecutionPlan, r.execution_plan_id) if r.execution_plan_id else None
    rd = (await db.execute(select(ModelRoutingDecision).where(ModelRoutingDecision.run_id == r.id).order_by(ModelRoutingDecision.created_at))).scalars().all()
    pd = (await db.execute(select(PolicyDecision).where(PolicyDecision.run_id == r.id).order_by(PolicyDecision.created_at))).scalars().all()
    cps = (await db.execute(select(Checkpoint).where(Checkpoint.run_id == r.id).order_by(Checkpoint.created_at))).scalars().all()
    ws = (await db.execute(select(WaitState).where(WaitState.run_id == r.id))).scalars().all()
    ca = (await db.execute(select(CompensationAction).where(CompensationAction.run_id == r.id).order_by(CompensationAction.sequence))).scalars().all()
    gp = (await db.execute(select(GoalPlan).where(GoalPlan.run_id == r.id).order_by(GoalPlan.version))).scalars().all()
    from isocline.engine.executor import callback_path
    s = r.settings or {}
    return {
        "plan": plan.plan if plan else None,
        "policy_rules": len(s.get("_policy") or []),
        "run_approval": s.get("_run_approval"),
        "routing": [dump(d, "id", "node_id", "scope", "objective", "selected_provider", "selected_model", "reasons", "candidates", "created_at") for d in rd],
        "policy_decisions": [dump(d, "id", "node_id", "kind", "subject", "action", "effect", "reason", "created_at") for d in pd],
        "checkpoints": [dump(c, "id", "node_id", "node_key", "reason", "created_at", nodes_complete=len(c.completed_node_runs or []),
                             artifacts=len(c.artifact_ids or [])) for c in cps],
        "waits": [dump(w, "id", "node_id", "scope", "kind", "status", "resume_at", "timeout_at", "timeout_action", "event_name",
                       "correlation_key", "created_at", "resolved_at",
                       callback_path=callback_path(str(r.id), w.node_id) if w.kind == "webhook" else None,
                       child_run_id=str(w.child_run_id) if w.child_run_id else None) for w in ws],
        "compensations": [dump(c, "id", "node_key", "sequence", "performed", "compensation", "status", "result", "attempted_at", "attempted_by") for c in ca],
        "goal_plans": [dump(g, "id", "version", "reason", "method", "plan", "graph", "validation", "created_at") for g in gp],
    }


class ResumeIn(BaseModel):
    checkpoint_id: str


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str, body: ResumeIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.runs import resume_from_checkpoint
    r = await load_run(db, user, run_id, "workflows:execute")
    wf, p = await load_workflow(db, user, r.workflow_id, "workflows:execute")
    child = await resume_from_checkpoint(db, r, parse_uuid(body.checkpoint_id, "Checkpoint"), workflow=wf, project=p, user_id=user.id)
    await audit(db, "run_resumed_from_checkpoint", user_id=user.id, workspace_id=p.workspace_id, target_id=child.id,
                data={"parent": str(r.id), "checkpoint": body.checkpoint_id}, commit=True)
    return {"run_id": str(child.id), "status": child.status}


class CompIn(BaseModel):
    action_ids: list[str] | None = None


@router.post("/runs/{run_id}/compensate")
async def compensate(run_id: str, body: CompIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Manually run registered compensations (a user triggering them counts as approval; deny policies still apply)."""
    from isocline.services.compensation import run_compensations
    r = await load_run(db, user, run_id, "admin")
    if r.status in ("queued", "running", "resuming"):
        raise AppError(409, "run_active", "Wait for the run to stop before compensating")
    res = await run_compensations(str(r.id), actor=str(user.id), only_ids=body.action_ids)
    return res


@router.get("/runs/{run_id}/lineage")
async def lineage(run_id: str, field: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.monitoring import run_lineage
    r = await load_run(db, user, run_id)
    return await run_lineage(db, r, field)


class DocumentIn(BaseModel):
    document: dict


@router.post("/projects/{project_id}/validate-document")
async def validate_document(project_id: str, body: DocumentIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Validates a workflow document (e.g. a file in a repo) without saving it: schema, structure, contracts,
    environment checks and the execution plan. Used by `isocline validate` in CI."""
    from isocline.api.deps import load_project
    from isocline.engine.budget import effective_settings
    from isocline.engine.planner import build_plan
    from isocline.engine.policy import apply_budget_clamps
    from isocline.schemas.workflow import WorkflowDocument
    from isocline.services.policies import snapshot
    from isocline.services.runs import resolve_library_agents
    from isocline.services.types_registry import custom_types_for
    from isocline.services.validation import validate_all
    p = await load_project(db, user, project_id)
    try:
        doc = WorkflowDocument.model_validate(body.document)
    except Exception as e:
        return {"valid": False, "status": "BLOCKED", "issues": [{"severity": "error", "code": "schema", "message": str(e)[:2000]}]}
    raw = await resolve_library_agents(db, doc.graph.model_dump(mode="json"), p.workspace_id)
    graph, issues = await validate_all(db, raw, p.workspace_id, p.id)
    plan = None
    if graph is not None:
        pol = await snapshot(db, workspace_id=p.workspace_id, project_id=p.id)
        plan = await build_plan(db, graph, workflow_id=None, workspace_id=p.workspace_id, project_id=p.id,
                                settings=apply_budget_clamps(effective_settings(graph.settings), pol), policy=pol,
                                custom_types=await custom_types_for(db, p.workspace_id))
    errors = [i for i in issues if i["severity"] == "error"] + ([{"severity": "error", "code": "preflight", "message": c["message"]}
                                                                  for c in plan["checks"] if c["status"] == "fail"] if plan else [])
    return {"valid": not errors, "status": plan["status"] if plan else "BLOCKED", "issues": issues, "plan": plan}


@router.get("/projects/{project_id}/workflow-lookup")
async def lookup(project_id: str, name: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.api.deps import load_project
    from isocline.db.models import Workflow
    p = await load_project(db, user, project_id)
    wf = (await db.execute(select(Workflow).where(Workflow.project_id == p.id, Workflow.name == name))).scalars().first()
    if wf is None:
        raise not_found("Workflow")
    return {"id": str(wf.id), "name": wf.name, "latest_version": wf.latest_version}
