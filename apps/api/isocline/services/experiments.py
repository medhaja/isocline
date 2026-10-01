"""Experiments (variant matrix over a dataset), the component playground (run one node or sub-workflow with mocked
upstream values) and contract tests (reusable component tests that gate publishing)."""
from __future__ import annotations

import copy
import itertools
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import bad_request
from isocline.db.models import EvaluationCase, EvaluationResult, EvaluationRun, NodeRun, Project, Run, ToolRun, Workflow
from isocline.db.models_v2 import ComponentTest, Experiment, ExperimentVariant
from isocline.services.ai_builder import _deep_merge


# ------------------------------------------------------------------------------------------ experiments
def variant_graph(base: dict, node_id: str | None, overrides: dict) -> dict:
    g = copy.deepcopy(base)
    targets = [n for n in g["nodes"] if (node_id is None and n["type"] == "agent") or n["id"] == node_id]
    if not targets:
        raise bad_request("The experiment node is no longer in the workflow")
    for n in targets:
        cfg = n.setdefault("config", {})
        for k in ("model", "prompt", "instructions", "params", "context", "knowledge_base_ids", "tools", "routing"):
            if k in overrides:
                cfg[k] = _deep_merge(cfg.get(k) or {}, overrides[k]) if isinstance(overrides[k], dict) and isinstance(cfg.get(k), dict) and k != "model" \
                    else overrides[k]
    return g


def matrix(dimensions: dict[str, list]) -> list[dict]:
    """{"model": [A, B], "prompt": [p1, p2]} → 4 variants named A1..B2 (model letter, prompt number)."""
    keys = [k for k, v in dimensions.items() if v]
    out = []
    for combo in itertools.product(*[dimensions[k] for k in keys]):
        ov = dict(zip(keys, combo))
        name = " · ".join(_label(k, v) for k, v in ov.items())
        out.append({"name": name[:120], "overrides": ov})
    return out


def _label(k, v):
    if k == "model" and isinstance(v, dict):
        return v.get("model", "?")
    if k == "prompt":
        return f"prompt “{str(v)[:24]}”"
    if k == "params" and isinstance(v, dict):
        return ", ".join(f"{a}={b}" for a, b in v.items())
    return f"{k}={json.dumps(v)[:30]}"


async def start_experiment(db: AsyncSession, exp: Experiment) -> None:
    from isocline.services.evaluation import enqueue_evaluation
    variants = (await db.execute(select(ExperimentVariant).where(ExperimentVariant.experiment_id == exp.id))).scalars().all()
    cases = (await db.execute(select(EvaluationCase).where(EvaluationCase.dataset_id == exp.dataset_id))).scalars().all()
    if not cases:
        raise bad_request("The dataset has no test cases")
    queued = []
    for v in variants:
        g = variant_graph(exp.base_graph, exp.node_id, v.overrides)
        er = EvaluationRun(dataset_id=exp.dataset_id, workflow_id=exp.workflow_id, status="running", summary={"cases": len(cases)},
                           graph=g, label=f"experiment:{exp.name}:{v.name}")
        db.add(er)
        await db.flush()
        for c in cases:
            db.add(EvaluationResult(evaluation_run_id=er.id, case_id=c.id, status="pending"))
        v.evaluation_run_id, v.metrics = er.id, {}
        queued.append(str(er.id))
    exp.status = "running"
    await db.commit()
    for q in queued:
        enqueue_evaluation(q)


async def variant_metrics(db: AsyncSession, er: EvaluationRun) -> dict:
    s = dict(er.summary or {})
    rows = (await db.execute(select(EvaluationResult.run_id).where(EvaluationResult.evaluation_run_id == er.id))).scalars().all()
    run_ids = [r for r in rows if r]
    runs = (await db.execute(select(Run).where(Run.id.in_(run_ids)))).scalars().all() if run_ids else []
    nodes = (await db.execute(select(NodeRun).where(NodeRun.run_id.in_(run_ids), NodeRun.node_type == "agent"))).scalars().all() if run_ids else []
    tools = (await db.execute(select(ToolRun.success).where(ToolRun.run_id.in_(run_ids)))).all() if run_ids else []
    lats = sorted((r.finished_at - r.started_at).total_seconds() for r in runs if r.finished_at and r.started_at)
    structured = [n for n in nodes if (n.config or {}).get("output_schema")]
    return {"status": er.status, "pass_rate": s.get("pass_rate"), "cases": s.get("cases"),
            "avg_cost_usd": round(sum(r.cost_usd or 0 for r in runs) / len(runs), 6) if runs else None,
            "p95_latency_s": round(lats[min(len(lats) - 1, int(0.95 * (len(lats) - 1)))], 2) if lats else None,
            "avg_tokens": int(sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in runs) / len(runs)) if runs else None,
            "failure_rate": round(sum(1 for r in runs if r.status == "failed") / len(runs), 4) if runs else None,
            "schema_compliance": round(sum(1 for n in structured if n.status == "completed") / len(structured), 4) if structured else None,
            "tool_success": round(sum(1 for (ok,) in tools if ok) / len(tools), 4) if tools else None,
            "model_based_evaluators": s.get("model_based_evaluators", False)}


def pareto(variants: list[dict]) -> set[str]:
    """Variants not dominated on (quality ↑, cost ↓, latency ↓). Never a single 'winner'.
    Differences within measurement noise (quality ±0.5pp, cost ±5%, latency ±max(0.25s, 10%)) count as ties."""
    pts = [(v["id"], v["metrics"].get("pass_rate"), v["metrics"].get("avg_cost_usd"), v["metrics"].get("p95_latency_s")) for v in variants]
    pts = [p for p in pts if None not in p[1:]]

    def better(x, y, kind):  # strictly better beyond noise
        if kind == "q":
            return x > y + 0.005
        if kind == "c":
            return x < y - max(1e-6, 0.05 * y)
        return x < y - max(0.25, 0.1 * y)

    def no_worse(x, y, kind):
        return not better(y, x, kind)
    front = set()
    for a in pts:
        dominated = any(b is not a and no_worse(b[1], a[1], "q") and no_worse(b[2], a[2], "c") and no_worse(b[3], a[3], "l")
                        and (better(b[1], a[1], "q") or better(b[2], a[2], "c") or better(b[3], a[3], "l")) for b in pts)
        if not dominated:
            front.add(a[0])
    return front


# ------------------------------------------------------------------------------------------ playground
def ancestors(graph: dict, node_id: str) -> set[str]:
    inc: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        inc.setdefault(e["target"], []).append(e["source"])
    seen, stack = set(), list(inc.get(node_id, []))
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack += inc.get(x, [])
    return seen


async def playground_run(db: AsyncSession, wf: Workflow, project: Project, node_id: str, run_input: Any, mocks: dict,
                         graph: dict | None = None, user_id=None) -> Run:
    """Runs one component in isolation: the node, its upstream closure (mocked nodes are not executed) and a
    capture output. Mocked outputs are pre-recorded, so the executor treats them as already completed."""
    from isocline.services.runs import create_run
    base = graph or wf.graph
    nodes = {n["id"]: n for n in base.get("nodes", [])}
    if node_id not in nodes:
        raise bad_request("Node not found in the workflow")
    target = nodes[node_id]
    keep = ancestors(base, node_id) | {node_id}
    mocked_ids = {n["id"] for n in nodes.values() if n["key"] in (mocks or {}) and n["id"] in keep}
    # upstream of a mocked node is not needed
    needed = {node_id}
    frontier = [node_id]
    while frontier:
        x = frontier.pop()
        for e in base.get("edges", []):
            if e["target"] == x and e["source"] in keep and e["source"] not in needed:
                needed.add(e["source"])
                if e["source"] not in mocked_ids:
                    frontier.append(e["source"])
    sub_nodes = []
    for i in needed:
        n = copy.deepcopy(nodes[i])
        if i in mocked_ids:  # stand-in entry node: same id/key, never executed (its output is pre-recorded)
            n.update({"type": "input_json", "config": {"field": f"__mock_{n['key']}", "required": False}, "contract": None,
                      "harness": {}, "name": f"{n.get('name') or n['key']} (mocked)"})
        sub_nodes.append(n)
    capture = {"id": "n___playground_out", "key": "playground_output", "type": "output_json", "name": "Playground output",
               "position": {"x": 0, "y": 0}, "config": {"format": "json"}}
    sub_edges = [copy.deepcopy(e) for e in base.get("edges", []) if e["source"] in needed and e["target"] in needed]
    sub_edges.append({"id": "e___playground", "source": node_id, "target": capture["id"], "source_handle": None, "target_handle": None})
    if target["type"] in ("output_text", "output_json", "output_file", "output_report", "output_api"):
        sub_edges.pop()
    else:
        sub_nodes.append(capture)
    g = {**base, "nodes": sub_nodes, "edges": sub_edges}
    run = await create_run(db, workflow=wf, project=project, run_input=run_input or {}, trigger="playground", graph_override=g,
                           dispatch=False, user_id=user_id, skip_plan=True)
    for nid in mocked_ids:
        n = nodes[nid]
        db.add(NodeRun(run_id=run.id, node_id=nid, node_key=n["key"], node_type=n["type"], scope="", status="completed",
                       input={"mocked": True},
                       output=mocks[n["key"]], attempts=[{"status": "mocked"}]))
    await db.commit()
    from isocline.services.dispatch import enqueue_run
    enqueue_run(str(run.id))
    return run


# ------------------------------------------------------------------------------------------ contract tests
def check_assertions(assertions: list[dict], output: Any, node: dict, custom_types: dict) -> list[dict]:
    from isocline.engine.expressions import Scope, resolve_value
    from isocline.engine.types import TypeError_, check_value, parse_type
    results = []
    for a in assertions:
        kind = a.get("type", "path")
        if kind == "schema_valid":
            t = ((node.get("contract") or {}).get("output") or {}).get("type") or "Any"
            try:
                errs = check_value(output, parse_type(t, custom_types), custom_types)
            except TypeError_ as e:
                errs = [str(e)]
            results.append({"assertion": f"output matches {t}", "passed": not errs, "detail": "; ".join(errs[:3])})
            continue
        if kind == "not_empty":
            results.append({"assertion": "output is not empty", "passed": output not in (None, "", [], {})})
            continue
        path = a.get("path") or ""
        val = resolve_value("{{x.output" + (("." + path) if path and not path.startswith("[") else path) + "}}", Scope({}, {"x": output})) if path else output
        op, target = a.get("op", "exists"), a.get("value")
        try:
            if op == "between":
                ok = float(target[0]) <= float(val) <= float(target[1])
            elif op == "exists":
                ok = val not in (None, "")
            elif op == "==":
                ok = val == target or str(val) == str(target)
            elif op == "contains":
                ok = str(target).lower() in json.dumps(val, default=str).lower()
            elif op in (">", ">=", "<", "<="):
                ok = {">": float(val) > float(target), ">=": float(val) >= float(target), "<": float(val) < float(target),
                      "<=": float(val) <= float(target)}[op]
            else:
                ok = False
        except (TypeError, ValueError, IndexError):
            ok = False
        results.append({"assertion": f"{path or 'output'} {op} {json.dumps(target) if target is not None else ''}".strip(), "passed": ok,
                        "actual": val if not isinstance(val, (dict, list)) else json.dumps(val)[:200]})
    return results


async def finalize_test(db: AsyncSession, t: ComponentTest, wf: Workflow) -> ComponentTest:
    if not t.last_run_id or t.last_status != "running":
        return t
    run = await db.get(Run, t.last_run_id)
    if run is None or run.status in ("queued", "running", "resuming"):
        return t
    node = next((n for n in (wf.graph or {}).get("nodes", []) if n["id"] == t.node_id), {})
    if run.status != "completed":
        t.last_status, t.last_details = "error", [{"assertion": "run completed", "passed": False,
                                                    "detail": (run.error or {}).get("message", run.status)}]
    else:
        nr = (await db.execute(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.node_id == t.node_id, NodeRun.scope == ""))).scalar_one_or_none()
        output = nr.output if nr else None
        from isocline.services.types_registry import custom_types_for
        project = await db.get(Project, wf.project_id)
        res = check_assertions(t.assertions or [{"type": "not_empty"}], output, node, await custom_types_for(db, project.workspace_id))
        t.last_details = res
        t.last_status = "passed" if all(r["passed"] for r in res) else "failed"
    await db.commit()
    return t


async def publish_gate(db: AsyncSession, wf: Workflow) -> list[str]:
    """Contract tests must pass on the exact graph being published."""
    from isocline.engine.planner import graph_hash
    tests = (await db.execute(select(ComponentTest).where(ComponentTest.workflow_id == wf.id))).scalars().all()
    if not tests:
        return []
    h = graph_hash(wf.graph)
    problems = []
    for t in tests:
        await finalize_test(db, t, wf)
        if t.last_graph_hash != h:
            problems.append(f"'{t.name}' has not run on the current draft")
        elif t.last_status != "passed":
            problems.append(f"'{t.name}' {t.last_status or 'has not run'}")
    return problems
