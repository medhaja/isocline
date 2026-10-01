from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_dataset, load_project, load_workflow, parse_uuid
from isocline.core.errors import bad_request, not_found
from isocline.db.models import (
    EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun, Run, User, Workflow, WorkflowVersion,
)
from isocline.db.session import get_db
from isocline.services.audit import audit
from isocline.services.evaluation import EVALUATOR_TYPES, enqueue_evaluation

router = APIRouter(tags=["evaluations"])


class Evaluator(BaseModel):
    model_config = {"extra": "allow"}
    type: str
    label: str | None = None


class CaseIn(BaseModel):
    name: str = Field(default="", max_length=200)
    input: Any = Field(default_factory=dict)
    expected: Any = None
    evaluators: list[Evaluator] = Field(default_factory=list)


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    cases: list[CaseIn] = Field(default_factory=list)


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class EvaluateIn(BaseModel):
    dataset_id: str
    version: int | None = None


def _check_evaluators(evs: list[Evaluator]) -> list[dict]:
    out = []
    for e in evs:
        if e.type not in EVALUATOR_TYPES:
            raise bad_request(f"Unknown evaluator '{e.type}'. Use one of: {', '.join(EVALUATOR_TYPES)}")
        if e.type == "llm_judge" and not (getattr(e, "model", None) or {}).get("model"):
            raise bad_request("LLM judge evaluators need a provider and model")
        if e.type == "custom_python" and not getattr(e, "code", None):
            raise bad_request("Custom Python evaluators need code defining evaluate(output, expected)")
        out.append(e.model_dump())
    return out


def case_out(c: EvaluationCase) -> dict:
    return dump(c, "id", "dataset_id", "name", "input", "expected", "evaluators", "created_at")


def er_out(er: EvaluationRun, **extra) -> dict:
    return dump(er, "id", "dataset_id", "workflow_id", "workflow_version_id", "status", "summary", "created_at", "finished_at", **extra)


@router.get("/evaluators")
async def evaluators(user: User = Depends(current_user)):
    return [{"type": "exact", "label": "Exact match", "model_based": False},
            {"type": "contains", "label": "Contains", "model_based": False},
            {"type": "json_schema", "label": "JSON schema", "model_based": False},
            {"type": "numeric", "label": "Numeric tolerance", "model_based": False},
            {"type": "semantic", "label": "Semantic similarity", "model_based": False},
            {"type": "custom_python", "label": "Custom Python (sandboxed)", "model_based": False},
            {"type": "llm_judge", "label": "LLM judge (model-based, not objective truth)", "model_based": True}]


@router.get("/projects/{project_id}/evaluation-datasets")
async def list_datasets(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    rows = (await db.execute(select(EvaluationDataset, func.count(EvaluationCase.id)).outerjoin(EvaluationCase)
                             .where(EvaluationDataset.project_id == p.id).group_by(EvaluationDataset.id)
                             .order_by(EvaluationDataset.created_at.desc()))).all()
    return [dump(d, "id", "project_id", "name", "description", "created_at", case_count=n) for d, n in rows]


@router.post("/projects/{project_id}/evaluation-datasets", status_code=201)
async def create_dataset(project_id: str, body: DatasetIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "editor")
    ds = EvaluationDataset(project_id=p.id, name=body.name, description=body.description)
    db.add(ds)
    await db.flush()
    for c in body.cases:
        db.add(EvaluationCase(dataset_id=ds.id, name=c.name, input=c.input, expected=c.expected, evaluators=_check_evaluators(c.evaluators)))
    await db.commit()
    return dump(ds, "id", "project_id", "name", "description", "created_at", case_count=len(body.cases))


@router.get("/evaluation-datasets/{dataset_id}")
async def get_dataset(dataset_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ds, _ = await load_dataset(db, user, dataset_id)
    cases = (await db.execute(select(EvaluationCase).where(EvaluationCase.dataset_id == ds.id).order_by(EvaluationCase.created_at))).scalars().all()
    return dump(ds, "id", "project_id", "name", "description", "created_at", cases=[case_out(c) for c in cases])


@router.patch("/evaluation-datasets/{dataset_id}")
async def patch_dataset(dataset_id: str, body: DatasetPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ds, _ = await load_dataset(db, user, dataset_id, "editor")
    if body.name is not None:
        ds.name = body.name
    if body.description is not None:
        ds.description = body.description
    await db.commit()
    return dump(ds, "id", "project_id", "name", "description", "created_at")


@router.delete("/evaluation-datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ds, _ = await load_dataset(db, user, dataset_id, "editor")
    await db.delete(ds)
    await db.commit()


@router.post("/evaluation-datasets/{dataset_id}/cases", status_code=201)
async def add_case(dataset_id: str, body: CaseIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ds, _ = await load_dataset(db, user, dataset_id, "editor")
    c = EvaluationCase(dataset_id=ds.id, name=body.name, input=body.input, expected=body.expected, evaluators=_check_evaluators(body.evaluators))
    db.add(c)
    await db.commit()
    return case_out(c)


async def _load_case(db, user, case_id) -> EvaluationCase:
    c = await db.get(EvaluationCase, parse_uuid(case_id, "Case"))
    if c is None:
        raise not_found("Case")
    await load_dataset(db, user, c.dataset_id, "editor")
    return c


@router.put("/evaluation-cases/{case_id}")
async def update_case(case_id: str, body: CaseIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _load_case(db, user, case_id)
    c.name, c.input, c.expected, c.evaluators = body.name, body.input, body.expected, _check_evaluators(body.evaluators)
    await db.commit()
    return case_out(c)


@router.delete("/evaluation-cases/{case_id}", status_code=204)
async def delete_case(case_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _load_case(db, user, case_id)
    await db.delete(c)
    await db.commit()


@router.post("/workflows/{workflow_id}/evaluate", status_code=202)
async def evaluate(workflow_id: str, body: EvaluateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "workflows:execute")
    ds, dp = await load_dataset(db, user, body.dataset_id)
    if dp.id != p.id:
        raise bad_request("Dataset belongs to a different project")
    cases = (await db.execute(select(EvaluationCase).where(EvaluationCase.dataset_id == ds.id))).scalars().all()
    if not cases:
        raise bad_request("Add at least one test case to the dataset")
    version = None
    if body.version is not None:
        version = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id,
                                                                  WorkflowVersion.version == body.version))).scalar_one_or_none()
        if version is None:
            raise not_found("Version")
    # Validate up-front so a broken workflow fails fast instead of per case.
    from isocline.services.runs import resolve_library_agents
    from isocline.services.validation import validate_all
    from isocline.core.errors import AppError
    _, issues = await validate_all(db, await resolve_library_agents(db, version.graph if version else wf.graph, p.workspace_id), p.workspace_id, p.id)
    errs = [i for i in issues if i["severity"] == "error"]
    if errs:
        raise AppError(422, "validation_failed", "Fix validation errors before evaluating", errs)
    er = EvaluationRun(dataset_id=ds.id, workflow_id=wf.id, workflow_version_id=version.id if version else None, status="running",
                       summary={"cases": len(cases)})
    db.add(er)
    await db.flush()
    for c in cases:
        db.add(EvaluationResult(evaluation_run_id=er.id, case_id=c.id, status="pending"))
    await audit(db, "evaluation_run", user_id=user.id, workspace_id=p.workspace_id, target_id=er.id)
    await db.commit()
    enqueue_evaluation(str(er.id))
    return er_out(er)


@router.get("/projects/{project_id}/evaluations")
async def project_evaluations(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    rows = (await db.execute(select(EvaluationRun, Workflow.name, EvaluationDataset.name).join(Workflow, Workflow.id == EvaluationRun.workflow_id)
                             .join(EvaluationDataset, EvaluationDataset.id == EvaluationRun.dataset_id)
                             .where(Workflow.project_id == p.id).order_by(EvaluationRun.created_at.desc()).limit(100))).all()
    return [er_out(e, workflow_name=w, dataset_name=d) for e, w, d in rows]


@router.get("/evaluations/{eval_id}")
async def get_evaluation(eval_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    er = await db.get(EvaluationRun, parse_uuid(eval_id, "Evaluation"))
    if er is None:
        raise not_found("Evaluation")
    wf, _ = await load_workflow(db, user, er.workflow_id)
    rows = (await db.execute(select(EvaluationResult, EvaluationCase, Run).join(EvaluationCase, EvaluationCase.id == EvaluationResult.case_id)
                             .outerjoin(Run, Run.id == EvaluationResult.run_id).where(EvaluationResult.evaluation_run_id == er.id)
                             .order_by(EvaluationCase.created_at))).all()
    results = []
    for r, c, run in rows:
        meta = next((s for s in (r.scores or []) if s.get("type") == "_meta"), {})
        results.append({"id": str(r.id), "case_id": str(c.id), "case_name": c.name, "input": c.input, "expected": c.expected,
                        "status": r.status, "scores": [s for s in (r.scores or []) if s.get("type") != "_meta"],
                        "run_id": str(run.id) if run else None, "output": (run.output or {}).get("result") if run and run.output else None,
                        "latency_ms": int((run.finished_at - run.started_at).total_seconds() * 1000) if run and run.finished_at and run.started_at else meta.get("latency_ms"),
                        "tokens": (run.input_tokens or 0) + (run.output_tokens or 0) if run else 0,
                        "cost_usd": run.cost_usd if run else 0})
    return er_out(er, workflow_name=wf.name, results=results)
