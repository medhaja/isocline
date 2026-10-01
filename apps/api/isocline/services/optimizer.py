"""Workflow Optimizer.

Analyze → propose patch → user reviews → candidate graph → evaluate (baseline vs candidate on a dataset) → compare →
user applies. Applying writes the candidate into the DRAFT as a new revision; it never publishes or promotes.

Recommendations are deterministic analyses of the graph plus measured history (node costs, latencies, retries,
repeated inputs, output-vs-input similarity, experiment results). Each carries evidence and an estimated impact.
Quality impact is never invented: it is "unknown until evaluated" unless experiment data exists."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError, conflict
from isocline.db.models import EvaluationRun, ModelPricing, NodeRun, Run, Workflow
from isocline.db.models_v2 import ExperimentVariant, OptimizationRecommendation, OptimizationRun
from isocline.engine.graph import compile_graph
from isocline.schemas.workflow import WorkflowGraph
from isocline.services.ai_builder import apply_operations, issues_for
from isocline.services.monitoring import node_breakdown

_REF = re.compile(r"\{\{\s*([a-zA-Z_]\w*)")


def _refs(cfg: dict) -> set[str]:
    return set(_REF.findall(json.dumps({k: v for k, v in (cfg or {}).items() if k in ("prompt", "instructions", "template", "arguments",
                                                                                   "rule", "routes", "content", "path", "mapping")})))


def critical_path(graph: dict, lat: dict[str, float]) -> float:
    g = WorkflowGraph.model_validate(graph)
    cg = compile_graph(g)
    best: dict[str, float] = {}
    for nid in cg.order:
        preds = [best.get(e.source, 0) for e in cg.incoming.get(nid, [])]
        best[nid] = max(preds, default=0) + lat.get(nid, 0)
    return max(best.values(), default=0)


async def analyze(db: AsyncSession, wf: Workflow, last: int = 30) -> OptimizationRun:
    graph = wf.graph
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    by_key = {n["key"]: n for n in nodes.values()}
    runs = (await db.execute(select(Run).where(Run.workflow_id == wf.id, Run.status == "completed", Run.trigger.notin_(("playground",)))
                             .order_by(Run.created_at.desc()).limit(last))).scalars().all()
    ids = [r.id for r in runs]
    stats = await node_breakdown(db, ids)
    nrs = (await db.execute(select(NodeRun).where(NodeRun.run_id.in_(ids), NodeRun.scope == ""))).scalars().all() if ids else []
    per_node_runs: dict[str, list[NodeRun]] = defaultdict(list)
    for nr in nrs:
        per_node_runs[nr.node_id].append(nr)
    lat = {nid: (s.get("latency_ms") or 0) / 1000 for nid, s in stats.items()}
    cost_per_run = sum(r.cost_usd or 0 for r in runs) / len(runs) if runs else 0.0
    calls_per_run = sum(r.llm_calls or 0 for r in runs) / len(runs) if runs else 0.0
    lat_per_run = critical_path(graph, lat) if stats else 0.0
    last_eval = (await db.execute(select(EvaluationRun).where(EvaluationRun.workflow_id == wf.id, EvaluationRun.status == "completed",
                                                              EvaluationRun.graph.is_(None)).order_by(EvaluationRun.created_at.desc()).limit(1))).scalar_one_or_none()
    quality = (last_eval.summary or {}).get("pass_rate") if last_eval else None
    current = {"cost_per_run": round(cost_per_run, 5), "latency_s": round(lat_per_run, 1), "llm_calls": round(calls_per_run, 1),
               "quality": quality, "runs_analyzed": len(runs), "cost_is_estimate": True}
    opt = OptimizationRun(workflow_id=wf.id, base_revision=wf.revision, current_metrics=current)
    db.add(opt)
    await db.flush()
    recs: list[OptimizationRecommendation] = []

    def add(kind, title, detail, evidence, ops, impact):
        recs.append(OptimizationRecommendation(optimization_run_id=opt.id, kind=kind, title=title, detail=detail, evidence=evidence,
                                               operations=ops, impact=impact))

    incoming, outgoing = defaultdict(list), defaultdict(list)
    for e in graph.get("edges", []):
        incoming[e["target"]].append(e)
        outgoing[e["source"]].append(e)
    total_cost = sum(s.get("cost", 0) for s in stats.values()) or 0

    # 1. sequential agents with no explicit data dependency → parallel
    for e in graph.get("edges", []):
        a, b = nodes.get(e["source"]), nodes.get(e["target"])
        if not a or not b or a["type"] != "agent" or b["type"] != "agent" or e.get("source_handle"):
            continue
        refs_b = _refs(b.get("config") or {})
        if len(incoming[b["id"]]) != 1 or a["key"] in refs_b:
            continue
        # Strong evidence only: B explicitly uses an earlier (non-input) upstream result instead of A's.
        # Without such a reference B may depend on A's output implicitly, so no recommendation.
        ancestors, stack = set(), [a["id"]]
        while stack:
            for x in incoming[stack.pop()]:
                if x["source"] not in ancestors:
                    ancestors.add(x["source"])
                    stack.append(x["source"])
        anc_keys = {nodes[x]["key"] for x in ancestors if x in nodes and not nodes[x]["type"].startswith(("input_", "trigger_"))}
        if not (refs_b & anc_keys):
            continue
        preds = [x["source"] for x in incoming[a["id"]]]
        if not preds:
            continue
        succs = [x["target"] for x in outgoing[b["id"]]]
        mkey = f"join_{a['key']}_{b['key']}"[:40]
        ops = [{"op": "remove_edge", "source": a["key"], "target": b["key"]}]
        ops += [{"op": "add_edge", "source": nodes[p]["key"], "target": b["key"]} for p in preds]
        ops += [{"op": "add_node", "node": {"key": mkey, "type": "merge", "name": "Merge", "config": {"strategy": "named"}}},
                {"op": "add_edge", "source": a["key"], "target": mkey}, {"op": "add_edge", "source": b["key"], "target": mkey}]
        for s in succs:
            ops += [{"op": "remove_edge", "source": b["key"], "target": nodes[s]["key"]}, {"op": "add_edge", "source": mkey, "target": nodes[s]["key"]}]
        saved = min(lat.get(a["id"], 0), lat.get(b["id"], 0))
        add("parallelize", f"{a['name'] or a['key']} and {b['name'] or b['key']} can run in parallel",
            f"{b['name'] or b['key']} uses {', '.join(sorted(refs_b & anc_keys))} directly and never references {a['key']}; it only receives "
            f"{a['key']}'s output implicitly. Running both from the same upstream removes a step from the critical path. Evaluate before applying.",
            {"references_of_" + b["key"]: sorted(_refs(b.get("config") or {})), "latency_s": {a["key"]: lat.get(a["id"]), b["key"]: lat.get(b["id"])}},
            ops, {"latency_s": -round(saved, 1), "cost_per_run": 0, "quality": "unknown until evaluated"})

    # 2. classifier agent → deterministic router
    for nid, n in nodes.items():
        if n["type"] != "agent":
            continue
        downs = [nodes[x["target"]] for x in outgoing[nid] if x["target"] in nodes]
        if not downs or not all(d["type"] in ("router", "condition") for d in downs):
            continue
        outs = [str(r.output).strip().lower() for r in per_node_runs.get(nid, []) if r.output is not None]
        labels = Counter(outs)
        s = stats.get(nid) or {}
        if len(outs) >= 5 and len(labels) <= 5 and all(len(l) <= 40 for l in labels):
            add("deterministic_logic", f"{n['name'] or n['key']} could be deterministic logic",
                f"Across {len(outs)} runs it produced only {len(labels)} distinct short labels ({', '.join(list(labels)[:5])}) consumed by "
                "a router/condition. If these labels follow deterministically from the input, a Router node with rules is free and "
                "instant. The optimizer cannot infer those rules safely, so this is a manual change.",
                {"labels": dict(labels.most_common(5)), "cost_per_call": s.get("cost"), "manual": True},
                [],
                {"cost_per_run": -round(s.get("cost", 0), 5), "latency_s": -round(lat.get(nid, 0), 1), "quality": "unknown until evaluated"})

    # 3. low-value node: large cost share, output ≈ input
    try:
        from isocline.services.embeddings import cosine, embed
    except Exception:
        embed = None
    for nid, n in nodes.items():
        s = stats.get(nid) or {}
        if n["type"] != "agent" or not total_cost or s.get("cost", 0) / total_cost < 0.12 or not incoming[nid] or not outgoing[nid]:
            continue
        pairs = [(json.dumps((r.input or {}).get("upstream"), default=str)[:6000], str(r.output)[:6000]) for r in per_node_runs.get(nid, [])[:8]
                 if isinstance(r.input, dict) and r.input.get("upstream")]
        if not pairs or embed is None:
            continue
        sims = []
        for a_txt, b_txt in pairs:
            va, vb = await embed([a_txt, b_txt])
            sims.append(cosine(va, vb))
        sim = sum(sims) / len(sims)
        if sim < 0.9:
            continue
        preds = [x["source"] for x in incoming[nid]]
        succs = [x["target"] for x in outgoing[nid]]
        ops = [{"op": "remove_node", "node_key": n["key"]}] + [{"op": "add_edge", "source": nodes[p]["key"], "target": nodes[t]["key"]}
                                                              for p in preds for t in succs]
        share = s["cost"] / total_cost
        add("remove_low_value", f"{n['name'] or n['key']} adds {share:.0%} of cost but changes little",
            f"On average its output is {sim:.0%} similar to its input (lexical/embedding similarity over {len(sims)} runs). "
            "Removing it saves its cost and latency; measure quality with an evaluation before applying.",
            {"cost_share": round(share, 3), "output_input_similarity": round(sim, 3)}, ops,
            {"cost_per_run": -round(s["cost"], 5), "latency_s": -round(lat.get(nid, 0), 1), "llm_calls": -1, "quality": "unknown until evaluated"})

    # 4. repeated large context
    for nid, n in nodes.items():
        s = stats.get(nid) or {}
        consumers = [nodes[x["target"]] for x in outgoing[nid] if nodes.get(x["target"], {}).get("type") == "agent"]
        out_tokens = sum((r.output_tokens or 0) for r in per_node_runs.get(nid, [])) / max(1, len(per_node_runs.get(nid, [])))
        if len(consumers) >= 2 and (out_tokens > 1200 or (s.get("tokens") or 0) > 4000):
            ops = [{"op": "update_node", "node_key": c["key"], "changes": {"config": {"context": {"sources": {"upstream": {"strategy": "extract", "max_tokens": 1500}}}}}}
                   for c in consumers]
            add("repeated_context", f"{n['name'] or n['key']}'s output is sent in full to {len(consumers)} agents",
                f"~{int(out_tokens):,} output tokens are copied into each consumer's context every run. Extracting the relevant sections "
                "(max 1,500 tokens each) reduces input tokens for every consumer.",
                {"consumers": [c["key"] for c in consumers], "avg_output_tokens": int(out_tokens)}, ops,
                {"input_tokens_per_run": -int(max(0, out_tokens - 1500) * len(consumers)), "quality": "unknown until evaluated"})

    # 5. cheaper model backed by experiment results (or flagged as a candidate to test)
    pricing = {(p.provider, p.model): p for p in (await db.execute(select(ModelPricing))).scalars()}
    variants = (await db.execute(select(ExperimentVariant))).scalars().all()
    measured = defaultdict(list)
    for v in variants:
        m = (v.overrides or {}).get("model") or {}
        if m.get("model") and isinstance((v.metrics or {}).get("pass_rate"), (int, float)):
            measured[(m["provider"], m["model"])].append(v.metrics["pass_rate"])
    for nid, n in nodes.items():
        if n["type"] != "agent":
            continue
        m = (n.get("config") or {}).get("model") or {}
        cur = pricing.get((m.get("provider"), m.get("model")))
        if not cur or cur.output_per_mtok is None:
            continue
        cur_q = (sum(measured[(m["provider"], m["model"])]) / len(measured[(m["provider"], m["model"])])) if measured.get((m.get("provider"), m.get("model"))) else None
        best = None
        for (p, mm), pr in pricing.items():
            if (p, mm) == (m.get("provider"), m.get("model")) or pr.output_per_mtok is None or p == "local_test":
                continue
            if pr.output_per_mtok >= cur.output_per_mtok * 0.6:
                continue
            caps = pr.capabilities or {}
            if (n["config"].get("tools") and not caps.get("tool_calling")) or (n["config"].get("output_schema") and not caps.get("structured_output")):
                continue
            q = sum(measured[(p, mm)]) / len(measured[(p, mm)]) if measured.get((p, mm)) else None
            if cur_q is not None and q is not None and q < cur_q - 0.02:
                continue
            if best is None or pr.output_per_mtok < best[1].output_per_mtok:
                best = ((p, mm), pr, q)
        if best and (stats.get(nid) or {}).get("cost", 0) > 0:
            (p, mm), pr, q = best
            ratio = (pr.output_per_mtok + (pr.input_per_mtok or 0)) / (cur.output_per_mtok + (cur.input_per_mtok or 0))
            node_cost = stats[nid]["cost"]
            evidence = {"current": f"{m['provider']}/{m['model']}", "candidate": f"{p}/{mm}", "price_ratio": round(ratio, 2)}
            if q is not None and cur_q is not None:
                evidence.update({"current_quality": cur_q, "candidate_quality": q})
                qual = f"experiments: {q:.0%} vs {cur_q:.0%}"
            else:
                qual = "unknown until evaluated"
            add("cheaper_model", f"{n['name'] or n['key']} could use {mm}",
                f"{mm} costs ~{ratio:.0%} of {m['model']} per token and meets this agent's capability needs." +
                (" Experiment results show comparable quality." if q is not None else " No experiment compares them yet — evaluate before applying."),
                evidence, [{"op": "update_node", "node_key": n["key"], "changes": {"config": {"model": {"provider": p, "model": mm}}}}],
                {"cost_per_run": -round(node_cost * (1 - ratio), 5), "quality": qual})

    # 6. checkpoint before a failure-prone expensive stage
    for nid, n in nodes.items():
        s = stats.get(nid) or {}
        if n["type"] != "agent" or s.get("runs", 0) < 3 or s.get("error_rate", 0) < 0.05:
            continue
        for pe in incoming[nid]:
            p = nodes.get(pe["source"])
            if p and p["type"] == "agent" and not (p.get("harness") or {}).get("checkpoint"):
                add("checkpoint", f"Add a checkpoint after {p['name'] or p['key']}",
                    f"{n['name'] or n['key']} fails in {s['error_rate']:.0%} of runs. A checkpoint after {p['key']} lets you resume "
                    "without paying for the upstream work again.", {"downstream_error_rate": s["error_rate"]},
                    [{"op": "update_node", "node_key": p["key"], "changes": {"harness": {"checkpoint": True}}}],
                    {"cost_per_failed_run": -round((stats.get(p["id"]) or {}).get("cost", 0), 5), "quality": "no effect"})

    # 7. exact cache where identical inputs recur
    for nid, n in nodes.items():
        if n["type"] not in ("agent", "tool_web_search", "tool_python", "tool_json", "tool_file_reader", "tool_vector_search"):
            continue
        if ((n.get("harness") or {}).get("cache") or {}).get("mode", "disabled") != "disabled":
            continue
        if n["type"] == "agent" and any(t == "http_request" or t.startswith("mcp:") for t in (n.get("config") or {}).get("tools") or []):
            continue
        hashes = [hashlib.sha256(json.dumps(r.input, sort_keys=True, default=str).encode()).hexdigest() for r in per_node_runs.get(nid, [])]
        if len(hashes) < 3:
            continue
        repeats = len(hashes) - len(set(hashes))
        if repeats / len(hashes) >= 0.2:
            s = stats.get(nid) or {}
            add("enable_cache", f"Enable exact caching for {n['name'] or n['key']}",
                f"{repeats} of its last {len(hashes)} executions had identical inputs. Exact caching reuses results for identical inputs "
                "only (24h TTL); side-effecting nodes are never cached.", {"repeat_ratio": round(repeats / len(hashes), 2)},
                [{"op": "update_node", "node_key": n["key"], "changes": {"harness": {"cache": {"mode": "exact", "ttl_seconds": 86400}}}}],
                {"cost_per_run": -round(s.get("cost", 0) * repeats / len(hashes), 5), "quality": "no effect (identical inputs)"})

    for r in recs:
        db.add(r)
    opt.projected_metrics = project(current, [r.impact for r in recs])
    await db.commit()
    return opt


def project(current: dict, impacts: list[dict]) -> dict:
    p = dict(current)
    for imp in impacts:
        for k in ("cost_per_run", "latency_s", "llm_calls"):
            if isinstance(imp.get(k), (int, float)) and p.get(k) is not None:
                p[k] = round(max(0.0, p[k] + imp[k]), 5 if k == "cost_per_run" else 1)
    p["quality"] = "measure with a candidate evaluation" if impacts else current.get("quality")
    return p


async def build_candidate(db: AsyncSession, opt: OptimizationRun, wf: Workflow, rec_ids: list[str]) -> dict:
    recs = (await db.execute(select(OptimizationRecommendation).where(OptimizationRecommendation.optimization_run_id == opt.id))).scalars().all()
    chosen = [r for r in recs if str(r.id) in rec_ids and r.operations]
    if not chosen:
        raise AppError(400, "nothing_selected", "Select at least one recommendation that includes a graph change")
    graph = wf.graph
    changes = []
    for r in recs:
        r.selected = r in chosen
    for r in chosen:
        ops = []
        for op in r.operations:
            if op.get("op") == "update_node" and "harness" in (op.get("changes") or {}):
                # harness lives on the node, not its config
                n = next((x for x in graph["nodes"] if x["key"] == op["node_key"]), None)
                if n is not None:
                    graph = json.loads(json.dumps(graph))
                    n = next(x for x in graph["nodes"] if x["key"] == op["node_key"])
                    from isocline.services.ai_builder import _deep_merge
                    n["harness"] = _deep_merge(n.get("harness") or {}, op["changes"]["harness"])
                    changes.append(f"Update {op['node_key']}: harness {', '.join(op['changes']['harness'])}")
                continue
            ops.append(op)
        graph, log = apply_operations(graph, ops, None)
        changes += log
    issues = issues_for(graph)
    opt.candidate_graph = graph
    opt.status = "candidate"
    opt.projected_metrics = project(opt.current_metrics, [r.impact for r in chosen])
    await db.commit()
    return {"graph": graph, "changes": changes, "issues": issues, "diff": _diff(wf.graph, graph), "projected": opt.projected_metrics}


def _diff(a: dict, b: dict) -> dict:
    return graph_diff(a, b)


def _m(ref):
    return f"{(ref or {}).get('provider')}/{(ref or {}).get('model')}" if ref else None


def _short(v, n=160):
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


def graph_diff(a: dict | None, b: dict | None) -> dict:
    """Node-level diff between two graphs (by node key)."""
    an = {n["key"]: n for n in (a or {}).get("nodes", [])}
    bn = {n["key"]: n for n in (b or {}).get("nodes", [])}
    added = [{"key": k, "name": bn[k].get("name"), "type": bn[k]["type"]} for k in bn.keys() - an.keys()]
    removed = [{"key": k, "name": an[k].get("name"), "type": an[k]["type"]} for k in an.keys() - bn.keys()]
    changed = []
    for k in an.keys() & bn.keys():
        x, y = an[k], bn[k]
        fields = []
        if x.get("name") != y.get("name"):
            fields.append({"field": "name", "from": x.get("name"), "to": y.get("name")})
        cx, cy = x.get("config") or {}, y.get("config") or {}
        if (cx.get("model") or {}).get("model") != (cy.get("model") or {}).get("model") or (cx.get("model") or {}).get("provider") != (cy.get("model") or {}).get("provider"):
            fields.append({"field": "model", "from": _m(cx.get("model")), "to": _m(cy.get("model"))})
        for f in ("prompt", "instructions", "role", "template"):
            if cx.get(f) != cy.get(f):
                fields.append({"field": f, "from": _short(cx.get(f)), "to": _short(cy.get(f))})
        for f in ("params", "tools", "output_schema", "retry", "context", "fallbacks", "knowledge_base_ids", "arguments", "rule", "routes"):
            if json.dumps(cx.get(f), sort_keys=True) != json.dumps(cy.get(f), sort_keys=True):
                fields.append({"field": f, "from": cx.get(f), "to": cy.get(f)})
        if json.dumps(x.get("contract"), sort_keys=True) != json.dumps(y.get("contract"), sort_keys=True):
            fields.append({"field": "contract", "from": x.get("contract"), "to": y.get("contract")})
        if json.dumps(x.get("harness"), sort_keys=True) != json.dumps(y.get("harness"), sort_keys=True):
            fields.append({"field": "harness", "from": x.get("harness"), "to": y.get("harness")})
        if (x.get("config") or {}).get("version") != (y.get("config") or {}).get("version") and x["type"] == "subworkflow":
            fields.append({"field": "sub-workflow version", "from": cx.get("version"), "to": cy.get("version")})
        if fields:
            changed.append({"key": k, "name": y.get("name"), "type": y["type"], "fields": fields})
    ea = {(e["source"], e["target"], e.get("source_handle")) for e in (a or {}).get("edges", [])}
    eb = {(e["source"], e["target"], e.get("source_handle")) for e in (b or {}).get("edges", [])}
    sa, sb = (a or {}).get("settings", {}), (b or {}).get("settings", {})
    settings = [{"field": k, "from": sa.get(k), "to": sb.get(k)} for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)]
    return {"added": added, "removed": removed, "changed": changed, "edges_added": len(eb - ea), "edges_removed": len(ea - eb),
            "settings": settings}


async def apply(db: AsyncSession, opt: OptimizationRun, wf: Workflow, user_id) -> Workflow:
    if not opt.candidate_graph:
        raise AppError(400, "no_candidate", "Build a candidate first")
    if wf.revision != opt.base_revision:
        raise conflict("The workflow changed after this analysis. Run the optimizer again.")
    wf.graph = opt.candidate_graph
    wf.revision += 1
    opt.status, opt.applied_by = "applied", user_id
    await db.commit()
    return wf
