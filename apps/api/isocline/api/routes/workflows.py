from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, load_workflow
from isocline.core.errors import AppError, bad_request, not_found
from isocline.db.models import Run, User, Workflow, WorkflowMemory, WorkflowVersion
from isocline.db.session import get_db
from isocline.schemas.workflow import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS, WorkflowDocument
from isocline.services.audit import audit
from isocline.services.runs import create_run, resolve_library_agents
from isocline.services.validation import parse_graph, validate_all
from isocline.services.workflows import WORKFLOW_TEMPLATES, build_template, export_document, fresh_ids, list_templates

router = APIRouter(tags=["workflows"])

EMPTY_GRAPH = {"schema_version": SCHEMA_VERSION, "nodes": [], "edges": [], "settings": {}}


class ModelRefIn(BaseModel):
    provider: str
    model: str
    credential_id: str | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    graph: dict | None = None
    template_id: str | None = None
    model: ModelRefIn | None = None  # model applied to every agent of a template


class WorkflowSave(BaseModel):
    graph: dict | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    revision: int  # optimistic concurrency: must equal the current revision


class StatusIn(BaseModel):
    status: Literal["draft", "archived"]


class PublishIn(BaseModel):
    notes: str = Field(default="", max_length=5000)


class ImportIn(BaseModel):
    document: dict


class RunIn(BaseModel):
    input: Any = Field(default_factory=dict)
    version: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)


class ValidateIn(BaseModel):
    graph: dict | None = None


def wf_out(wf: Workflow, full: bool = False) -> dict:
    d = dump(wf, "id", "project_id", "name", "description", "status", "revision", "latest_version", "created_at", "updated_at",
             node_count=len((wf.graph or {}).get("nodes", [])))
    if full:
        d["graph"] = wf.graph
    return d


def _check_graph(raw: dict) -> dict:
    graph, issues = parse_graph(raw)
    if graph is None:
        raise AppError(422, "invalid_graph", "The workflow document does not match schema v1.0", issues and [i.as_dict() for i in issues])
    return graph.model_dump(mode="json")


@router.get("/templates")
async def templates(user: User = Depends(current_user)):
    return list_templates()


@router.get("/projects/{project_id}/workflows")
async def list_workflows(project_id: str, include_archived: bool = False, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    q = select(Workflow).where(Workflow.project_id == p.id)
    if not include_archived:
        q = q.where(Workflow.status != "archived")
    wfs = (await db.execute(q.order_by(Workflow.updated_at.desc()))).scalars().all()
    last = dict((await db.execute(select(Run.workflow_id, func.max(Run.created_at)).where(Run.project_id == p.id)
                                  .group_by(Run.workflow_id))).all())
    return [{**wf_out(w), "last_run_at": last[w.id].isoformat() if w.id in last else None} for w in wfs]


@router.post("/projects/{project_id}/workflows", status_code=201)
async def create_workflow(project_id: str, body: WorkflowCreate, request: Request, user: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "editor")
    if body.template_id:
        if body.template_id not in WORKFLOW_TEMPLATES:
            raise not_found("Template")
        graph = build_template(body.template_id, body.model.model_dump() if body.model else {"provider": "", "model": ""})
    else:
        graph = _check_graph(body.graph) if body.graph else dict(EMPTY_GRAPH)
    wf = Workflow(project_id=p.id, name=body.name, description=body.description, graph=graph, created_by=user.id)
    db.add(wf)
    await db.flush()
    await audit(db, "workflow_created", user_id=user.id, workspace_id=p.workspace_id, target_type="workflow", target_id=wf.id)
    if body.template_id:
        await audit(db, "template_used", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id, data={"template": body.template_id})
    await db.commit()
    return wf_out(wf, full=True)


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id)
    return {**wf_out(wf, full=True), "workspace_id": str(p.workspace_id), "project_name": p.name}


@router.put("/workflows/{workflow_id}")
async def save_workflow(workflow_id: str, body: WorkflowSave, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Autosave. Rejects stale revisions instead of silently overwriting newer edits."""
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    if body.revision != wf.revision:
        raise AppError(409, "revision_conflict", "This workflow was changed elsewhere. Reload to get the latest version.",
                       {"current_revision": wf.revision})
    if body.graph is not None:
        wf.graph = _check_graph(body.graph)
    if body.name is not None:
        wf.name = body.name
    if body.description is not None:
        wf.description = body.description
    wf.revision += 1
    await db.commit()
    return wf_out(wf)


@router.patch("/workflows/{workflow_id}/status")
async def set_status(workflow_id: str, body: StatusIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    wf.status = body.status if not (body.status == "draft" and wf.latest_version) else "published"
    await audit(db, f"workflow_{body.status}", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id)
    await db.commit()
    return wf_out(wf)


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "admin")
    await audit(db, "workflow_deleted", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id, data={"name": wf.name})
    await db.delete(wf)
    await db.commit()


@router.post("/workflows/{workflow_id}/duplicate", status_code=201)
async def duplicate(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    copy_ = Workflow(project_id=p.id, name=f"{wf.name} (copy)", description=wf.description, graph=fresh_ids(wf.graph), created_by=user.id)
    db.add(copy_)
    await db.commit()
    return wf_out(copy_)


@router.post("/workflows/{workflow_id}/validate")
async def validate(workflow_id: str, body: ValidateIn | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id)
    raw = body.graph if body and body.graph is not None else wf.graph
    try:
        raw = await resolve_library_agents(db, raw, p.workspace_id)
    except AppError as e:
        return {"valid": False, "issues": [{"severity": "error", "code": "library_agent", "message": e.detail["message"]}]}
    g, issues = await validate_all(db, raw, p.workspace_id, p.id)
    if g is not None and g.settings.mode == "goal":  # the planner builds the graph at run time
        issues = [i for i in issues if i["code"] not in ("empty_workflow", "no_output")]
        if not (g.settings.goal and g.settings.goal.goal.strip()):
            issues.append({"severity": "error", "code": "goal_missing", "message": "Goal Mode needs a goal (workflow settings)"})
    return {"valid": not any(i["severity"] == "error" for i in issues), "issues": issues}


# ------------------------------------------------------------------ versions
@router.get("/workflows/{workflow_id}/versions")
async def versions(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id)
                             .order_by(WorkflowVersion.version.desc()))).scalars().all()
    return [dump(v, "id", "version", "notes", "created_at", node_count=len(v.graph.get("nodes", []))) for v in rows]


@router.get("/workflows/{workflow_id}/versions/{version}")
async def get_version(workflow_id: str, version: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    v = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == version))).scalar_one_or_none()
    if v is None:
        raise not_found("Version")
    return dump(v, "id", "version", "notes", "created_at", "graph")


@router.post("/workflows/{workflow_id}/publish", status_code=201)
async def publish(workflow_id: str, body: PublishIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Publishing snapshots the validated draft into an immutable version (library agents resolved)."""
    wf, p = await load_workflow(db, user, workflow_id, "workflows:publish")
    raw = await resolve_library_agents(db, wf.graph, p.workspace_id)
    graph, issues = await validate_all(db, raw, p.workspace_id, p.id)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise AppError(422, "validation_failed", "Fix validation errors before publishing", errors)
    from isocline.services.experiments import publish_gate
    failing = await publish_gate(db, wf)
    if failing:
        raise AppError(422, "contract_tests_failed", "Contract tests must pass on this draft before publishing",
                       [{"severity": "error", "code": "contract_test", "message": m} for m in failing])
    wf.latest_version += 1
    v = WorkflowVersion(workflow_id=wf.id, version=wf.latest_version, graph=graph.model_dump(mode="json"), notes=body.notes, created_by=user.id)
    db.add(v)
    wf.status = "published"
    await audit(db, "workflow_published", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id, data={"version": v.version})
    await db.commit()
    return dump(v, "id", "version", "notes", "created_at")


@router.post("/workflows/{workflow_id}/versions/{version}/restore")
async def restore(workflow_id: str, version: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Copies an old version into the draft. The version itself is never modified."""
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    v = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == version))).scalar_one_or_none()
    if v is None:
        raise not_found("Version")
    wf.graph = v.graph
    wf.revision += 1
    await audit(db, "workflow_restored", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id, data={"version": version})
    await db.commit()
    return wf_out(wf, full=True)


# ------------------------------------------------------------------ import / export
@router.get("/workflows/{workflow_id}/export")
async def export(workflow_id: str, version: int | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id)
    graph = wf.graph
    if version is not None:
        v = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == version))).scalar_one_or_none()
        if v is None:
            raise not_found("Version")
        graph = v.graph
    graph = await resolve_library_agents(db, graph, p.workspace_id)
    doc = export_document(wf.name, wf.description, graph)
    fname = "".join(c if c.isalnum() else "-" for c in wf.name.lower()).strip("-") or "workflow"
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{fname}.workflow.json"'})


@router.post("/projects/{project_id}/workflows/import", status_code=201)
async def import_workflow(project_id: str, body: ImportIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Imported workflows are validated and saved as drafts. They are never executed automatically."""
    p = await load_project(db, user, project_id, "editor")
    doc = body.document
    if doc.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS | {None}:
        raise bad_request(f"Unsupported schema version {doc.get('schema_version')}; supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}")
    try:
        parsed = WorkflowDocument.model_validate(doc)
    except Exception as e:
        raise AppError(422, "invalid_document", "This file is not a valid Isocline workflow", str(e)[:2000]) from e
    from isocline.services.workflows import strip_secrets
    graph = fresh_ids(strip_secrets(parsed.graph.model_dump(mode="json")))
    wf = Workflow(project_id=p.id, name=parsed.name[:200], description=parsed.description, graph=graph, created_by=user.id)
    db.add(wf)
    await db.flush()
    _, issues = await validate_all(db, graph, p.workspace_id, p.id)
    await audit(db, "workflow_imported", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id)
    await db.commit()
    return {**wf_out(wf), "issues": issues}


# ------------------------------------------------------------------ execution
@router.post("/workflows/{workflow_id}/run", status_code=202)
async def run_workflow(workflow_id: str, body: RunIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    wf, p = await load_workflow(db, user, workflow_id, "workflows:execute")
    version = None
    if body.version is not None:
        version = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id,
                                                                  WorkflowVersion.version == body.version))).scalar_one_or_none()
        if version is None:
            raise not_found("Version")
    run = await create_run(db, workflow=wf, project=p, run_input=body.input if body.input is not None else {}, user_id=user.id,
                           version=version, idempotency_key=body.idempotency_key or idempotency_key)
    await audit(db, "workflow_run", user_id=user.id, workspace_id=p.workspace_id, target_id=run.id, commit=True)
    return {"run_id": str(run.id), "status": run.status}


@router.get("/workflows/{workflow_id}/memory")
async def get_memory(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(WorkflowMemory).where(WorkflowMemory.workflow_id == wf.id))).scalars().all()
    return [dump(r, "key", "value", "updated_at") for r in rows]


@router.delete("/workflows/{workflow_id}/memory")
async def clear_memory(workflow_id: str, key: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    q = delete(WorkflowMemory).where(WorkflowMemory.workflow_id == wf.id)
    if key:
        q = q.where(WorkflowMemory.key == key)
    await db.execute(q)
    await audit(db, "workflow_memory_cleared", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id, data={"key": key})
    await db.commit()
    return {"ok": True}
