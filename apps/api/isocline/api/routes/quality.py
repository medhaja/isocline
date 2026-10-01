"""Experiments, component playground, contract tests and the Workflow Optimizer."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_dataset, load_run, load_workflow, parse_uuid
from isocline.core.errors import bad_request, not_found
from isocline.db.models import EvaluationCase, EvaluationResult, EvaluationRun, User
from isocline.db.models_v2 import ComponentTest, Experiment, ExperimentVariant, OptimizationRecommendation, OptimizationRun
from isocline.db.session import get_db
from isocline.services import experiments as ex
from isocline.services import optimizer as opt_svc
from isocline.services.audit import audit

router = APIRouter(tags=["quality"])


# ================================================================== experiments
class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_id: str
    node_id: str | None = None  # None = every agent
    dimensions: dict[str, list[Any]] = Field(default_factory=dict)  # model / prompt / params / context / knowledge_base_ids / tools
    variants: list[dict] | None = None  # explicit [{name, overrides}] instead of a matrix


async def exp_out(db, e: Experiment) -> dict:
    vs = (await db.execute(select(ExperimentVariant).where(ExperimentVariant.experiment_id == e.id).order_by(ExperimentVariant.created_at))).scalars().all()
    out = []
    done = True
    for v in vs:
        m = v.metrics or {}
        if v.evaluation_run_id:
            er = await db.get(EvaluationRun, v.evaluation_run_id)
            if er:
                m = await ex.variant_metrics(db, er)
                if er.status == "completed" and v.metrics != m:
                    v.metrics = m
                done = done and er.status == "completed"
        out.append(dump(v, "id", "name", "overrides", created_at=v.created_at.isoformat(), metrics=m,
                        evaluation_run_id=str(v.evaluation_run_id) if v.evaluation_run_id else None))
    if e.status == "running" and done and vs:
        e.status = "completed"
    await db.commit()
    front = ex.pareto(out)
    for v in out:
        v["pareto"] = v["id"] in front
    return dump(e, "id", "workflow_id", "node_id", "name", "status", "created_at", dataset_id=str(e.dataset_id), variants=out,
                note="Pareto-efficient variants are not dominated on quality, cost and latency. No single variant is labelled best.")


@router.get("/workflows/{workflow_id}/experiments")
async def list_experiments(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(Experiment).where(Experiment.workflow_id == wf.id).order_by(Experiment.created_at.desc()))).scalars().all()
    return [await exp_out(db, e) for e in rows]


@router.post("/workflows/{workflow_id}/experiments", status_code=201)
async def create_experiment(workflow_id: str, body: ExperimentIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    ds, dp = await load_dataset(db, user, body.dataset_id)
    if dp.id != p.id:
        raise bad_request("Dataset belongs to another project")
    variants = body.variants or ex.matrix(body.dimensions)
    if not variants:
        raise bad_request("Add at least one variant (e.g. two models)")
    if len(variants) > 12:
        raise bad_request("At most 12 variants per experiment")
    for v in variants:
        ex.variant_graph(wf.graph, body.node_id, v.get("overrides") or {})  # validates the node exists
    e = Experiment(project_id=p.id, workflow_id=wf.id, node_id=body.node_id, dataset_id=ds.id, name=body.name, base_graph=wf.graph)
    db.add(e)
    await db.flush()
    for v in variants:
        db.add(ExperimentVariant(experiment_id=e.id, name=str(v.get("name") or "variant")[:120], overrides=v.get("overrides") or {}))
    await db.commit()
    return await exp_out(db, e)


@router.post("/experiments/{exp_id}/start", status_code=202)
async def start_experiment(exp_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Experiment, parse_uuid(exp_id, "Experiment"))
    if e is None:
        raise not_found("Experiment")
    _, p = await load_workflow(db, user, e.workflow_id, "editor")
    await ex.start_experiment(db, e)
    await audit(db, "experiment_started", user_id=user.id, workspace_id=p.workspace_id, target_id=e.id, commit=True)
    return await exp_out(db, e)


@router.get("/experiments/{exp_id}")
async def get_experiment(exp_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    e = await db.get(Experiment, parse_uuid(exp_id, "Experiment"))
    if e is None:
        raise not_found("Experiment")
    await load_workflow(db, user, e.workflow_id)
    return await exp_out(db, e)


# ================================================================== playground & contract tests
class PlaygroundIn(BaseModel):
    input: Any = Field(default_factory=dict)
    mocks: dict[str, Any] = Field(default_factory=dict)
    graph: dict | None = None


@router.post("/workflows/{workflow_id}/nodes/{node_id}/playground", status_code=202)
async def playground(workflow_id: str, node_id: str, body: PlaygroundIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    run = await ex.playground_run(db, wf, p, node_id, body.input, body.mocks, body.graph, user.id)
    return {"run_id": str(run.id), "status": run.status}


class TestIn(BaseModel):
    node_id: str
    name: str = Field(min_length=1, max_length=200)
    run_input: Any = Field(default_factory=dict)
    mocks: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict] = Field(default_factory=lambda: [{"type": "schema_valid"}])


def test_out(t: ComponentTest) -> dict:
    return dump(t, "id", "node_id", "name", "run_input", "mocks", "assertions", "last_status", "last_details", "last_graph_hash", "created_at",
                last_run_id=str(t.last_run_id) if t.last_run_id else None)


@router.get("/workflows/{workflow_id}/tests")
async def list_tests(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.engine.planner import graph_hash
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(ComponentTest).where(ComponentTest.workflow_id == wf.id).order_by(ComponentTest.created_at))).scalars().all()
    h = graph_hash(wf.graph)
    out = []
    for t in rows:
        t = await ex.finalize_test(db, t, wf)
        out.append({**test_out(t), "current": t.last_graph_hash == h})
    return out


@router.post("/workflows/{workflow_id}/tests", status_code=201)
async def create_test(workflow_id: str, body: TestIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id, "editor")
    if body.node_id not in {n["id"] for n in wf.graph.get("nodes", [])}:
        raise not_found("Node")
    t = ComponentTest(workflow_id=wf.id, **body.model_dump())
    db.add(t)
    await db.commit()
    return test_out(t)


@router.delete("/tests/{test_id}", status_code=204)
async def delete_test(test_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(ComponentTest, parse_uuid(test_id, "Test"))
    if t is None:
        raise not_found("Test")
    await load_workflow(db, user, t.workflow_id, "editor")
    await db.delete(t)
    await db.commit()


@router.post("/workflows/{workflow_id}/tests/run", status_code=202)
async def run_tests(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.engine.planner import graph_hash
    wf, p = await load_workflow(db, user, workflow_id, "editor")
    tests = (await db.execute(select(ComponentTest).where(ComponentTest.workflow_id == wf.id))).scalars().all()
    if not tests:
        raise bad_request("Add a contract test first")
    h = graph_hash(wf.graph)
    started = []
    for t in tests:
        run = await ex.playground_run(db, wf, p, t.node_id, t.run_input, t.mocks, None, user.id)
        t = await db.get(ComponentTest, t.id)
        t.last_run_id, t.last_status, t.last_graph_hash, t.last_details = run.id, "running", h, []
        await db.commit()
        started.append(str(run.id))
    return {"runs": started}


# ================================================================== optimizer
async def opt_out(db, o: OptimizationRun) -> dict:
    recs = (await db.execute(select(OptimizationRecommendation).where(OptimizationRecommendation.optimization_run_id == o.id))).scalars().all()
    evals = {}
    for k, eid in (("baseline", o.baseline_eval_id), ("candidate", o.candidate_eval_id)):
        if eid:
            er = await db.get(EvaluationRun, eid)
            evals[k] = await ex.variant_metrics(db, er) if er else None
    if o.status == "evaluating" and evals and all(v and v["status"] == "completed" for v in evals.values()):
        o.status = "evaluated"
        await db.commit()
    return dump(o, "id", "workflow_id", "status", "base_revision", "current_metrics", "projected_metrics", "created_at",
                has_candidate=o.candidate_graph is not None, evaluations=evals,
                recommendations=[dump(r, "id", "kind", "title", "detail", "evidence", "operations", "impact", "selected",
                                      patchable=bool(r.operations)) for r in recs],
                safety="The optimizer never changes production. Applying writes a new draft revision; publishing and promotion stay manual.")


@router.post("/workflows/{workflow_id}/optimize", status_code=201)
async def optimize(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id, "editor")
    o = await opt_svc.analyze(db, wf)
    return await opt_out(db, o)


@router.get("/workflows/{workflow_id}/optimizations")
async def list_opts(workflow_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(OptimizationRun).where(OptimizationRun.workflow_id == wf.id).order_by(OptimizationRun.created_at.desc()).limit(10))).scalars().all()
    return [await opt_out(db, o) for o in rows]


async def _opt(db, user, opt_id, role="viewer"):
    o = await db.get(OptimizationRun, parse_uuid(opt_id, "Optimization"))
    if o is None:
        raise not_found("Optimization")
    wf, p = await load_workflow(db, user, o.workflow_id, role)
    return o, wf, p


@router.get("/optimizations/{opt_id}")
async def get_opt(opt_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    o, _, _ = await _opt(db, user, opt_id)
    return await opt_out(db, o)


class CandidateIn(BaseModel):
    recommendation_ids: list[str]


@router.post("/optimizations/{opt_id}/candidate")
async def candidate(opt_id: str, body: CandidateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    o, wf, _ = await _opt(db, user, opt_id, "editor")
    return await opt_svc.build_candidate(db, o, wf, body.recommendation_ids)


class OptEvalIn(BaseModel):
    dataset_id: str


@router.post("/optimizations/{opt_id}/evaluate", status_code=202)
async def evaluate_candidate(opt_id: str, body: OptEvalIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Evaluates the current draft and the candidate on the same dataset, side by side."""
    from isocline.services.evaluation import enqueue_evaluation
    o, wf, p = await _opt(db, user, opt_id, "editor")
    if not o.candidate_graph:
        raise bad_request("Build a candidate first")
    ds, dp = await load_dataset(db, user, body.dataset_id)
    cases = (await db.execute(select(EvaluationCase).where(EvaluationCase.dataset_id == ds.id))).scalars().all()
    if not cases:
        raise bad_request("The dataset has no test cases")
    ids = []
    for label, g in (("baseline", wf.graph), ("candidate", o.candidate_graph)):
        er = EvaluationRun(dataset_id=ds.id, workflow_id=wf.id, status="running", summary={"cases": len(cases)}, graph=g, label=f"optimizer:{label}")
        db.add(er)
        await db.flush()
        for c in cases:
            db.add(EvaluationResult(evaluation_run_id=er.id, case_id=c.id, status="pending"))
        ids.append(er.id)
    o.baseline_eval_id, o.candidate_eval_id, o.status = ids[0], ids[1], "evaluating"
    await db.commit()
    for i in ids:
        enqueue_evaluation(str(i))
    return await opt_out(db, o)


@router.post("/optimizations/{opt_id}/apply")
async def apply_opt(opt_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    o, wf, p = await _opt(db, user, opt_id, "editor")
    wf = await opt_svc.apply(db, o, wf, user.id)
    await audit(db, "optimizer_applied", user_id=user.id, workspace_id=p.workspace_id, target_id=wf.id,
                data={"optimization": str(o.id), "revision": wf.revision}, commit=True)
    return {"workflow_id": str(wf.id), "revision": wf.revision, "note": "Applied to the draft. Publish and promote when ready."}


# ================================================================== monitoring
@router.get("/workflows/{workflow_id}/heatmap")
async def heatmap(workflow_id: str, run_id: str | None = None, last: int = 20, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.monitoring import heatmap as hm
    wf, _ = await load_workflow(db, user, workflow_id)
    if run_id:
        await load_run(db, user, run_id)
    return await hm(db, wf.id, run_id, min(last, 200))
