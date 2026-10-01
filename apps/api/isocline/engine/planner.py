"""Execution planning & preflight.

The plan is computed from the graph, the capability/pricing registry and this workflow's own history (per-node
averages over recent runs), falling back to conservative priors. Ranges are honest: min assumes one call per agent and
short outputs; max assumes tool loops, structured-output repairs and retries. Latency is the critical path.
Preflight categorises every check and returns READY or BLOCKED; nothing expensive runs when BLOCKED."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import ModelPricing, NodeRun, Run, WorkflowVersion, utcnow
from isocline.engine.graph import compile_graph, validate_contracts, validate_structure
from isocline.engine.policy import evaluate_model, evaluate_tool, tool_action, approval_rules_triggered
from isocline.engine.pricing import estimate_cost, estimate_tokens
from isocline.engine.router import capability_gaps, required_capabilities, route
from isocline.schemas.workflow import WorkflowGraph

CATEGORIES = ["Structure", "Contracts & types", "Models & capabilities", "Credentials", "Policies", "Budgets",
              "Knowledge", "Context", "Sub-workflows"]
ENV_CODES = {"credential_missing": "Credentials", "credential_mismatch": "Credentials", "base_url_missing": "Credentials",
             "search_credential_missing": "Credentials", "secret_missing": "Credentials", "unknown_provider": "Models & capabilities",
             "model_unknown": "Models & capabilities", "kb_missing": "Knowledge", "kb_not_found": "Knowledge",
             "sandbox_unavailable": "Credentials"}


def graph_hash(raw: dict) -> str:
    g = {k: v for k, v in raw.items() if k != "schema_version"}
    g["nodes"] = [{k: v for k, v in n.items() if k != "position"} for n in raw.get("nodes", [])]
    return hashlib.sha256(json.dumps(g, sort_keys=True, default=str).encode()).hexdigest()


async def node_history(db: AsyncSession, workflow_id) -> dict[str, dict]:
    since = utcnow() - timedelta(days=30)
    rows = (await db.execute(
        select(NodeRun.node_key, func.count(NodeRun.id), func.avg(NodeRun.input_tokens), func.avg(NodeRun.output_tokens),
               func.avg(NodeRun.latency_ms), func.avg(NodeRun.cost_usd), func.avg(NodeRun.llm_calls))
        .join(Run, Run.id == NodeRun.run_id)
        .where(Run.workflow_id == workflow_id, NodeRun.status == "completed", NodeRun.started_at >= since,
               NodeRun.cache_status.is_distinct_from("hit"))
        .group_by(NodeRun.node_key))).all()
    return {k: {"runs": n, "in": float(i or 0), "out": float(o or 0), "latency_ms": float(l or 0), "cost": float(c or 0),
                "calls": float(lc or 0)} for k, n, i, o, l, c, lc in rows}


async def build_plan(db: AsyncSession, graph: WorkflowGraph, *, workflow_id, workspace_id, project_id, settings: dict,
                     policy: list[dict], env_issues: list[dict] | None = None, custom_types: dict | None = None,
                     _depth: int = 0) -> dict:
    from isocline.services.model_intel import load_candidates
    hist = await node_history(db, workflow_id) if workflow_id else {}
    pricing_rows = {(r.provider, r.model): r for r in (await db.execute(select(ModelPricing))).scalars()}
    cands = await load_candidates(db, workspace_id)
    checks: list[dict] = []

    def check(cat: str, status: str, message: str, node_id: str | None = None):
        checks.append({"category": cat, "status": status, "message": message, **({"node_id": node_id} if node_id else {})})

    # ---- structure & contracts
    if graph.settings.mode == "goal":
        g = graph.settings.goal
        if not g or not g.goal.strip():
            check("Structure", "fail", "Goal Mode needs a goal")
        else:
            check("Structure", "pass", f"Goal Mode: the planner composes up to {g.max_planning_depth} steps from {len(g.agents) or 'any'} agent type(s)")
        cg = None
    else:
        for i in validate_structure(graph):
            check("Structure", "fail" if i.severity == "error" else "warn", i.message, i.node_id)
        for i in validate_contracts(graph, custom_types or {}):
            check("Contracts & types", "fail" if i.severity == "error" else "warn", i.message, i.node_id)
        cg = compile_graph(graph)
    for i in env_issues or []:
        cat = ENV_CODES.get(i.get("code"), "Structure")
        if cat == "Structure" and i.get("code") in ("illegal_cycle",):
            continue
        check(cat, "fail" if i["severity"] == "error" else "warn", i["message"], i.get("node_id"))

    per_node: dict[str, dict] = {}
    approvals_possible = 0
    waits = 0
    nodes = {n.id: n for n in graph.nodes if n.executable}
    for n in nodes.values():
        h = hist.get(n.key)
        est: dict[str, Any] = {"key": n.key, "name": n.name or n.key, "type": n.type, "calls": [0, 0], "in_tokens": [0, 0],
                               "out_tokens": [0, 0], "cost": [0.0, 0.0], "latency_s": [0.05, 0.2], "source": "prior"}
        if n.type == "agent":
            c = n.config
            model = c.get("model") or {}
            tools = c.get("tools") or []
            structured = bool(c.get("output_schema")) or bool(n.contract and n.contract.output.type.startswith("JSON<"))
            req = required_capabilities(n.contract.capabilities if n.contract else [], tools, structured)
            base_in = estimate_tokens((c.get("instructions") or "") + (c.get("prompt") or "") + (c.get("role") or "")) + 350
            base_in += 150 * len(tools) + (300 * ((c.get("context") or {}).get("retrieval_top_k", 5)) if c.get("knowledge_base_ids") else 0)
            est["_base_in"] = base_in
            if model.get("provider") == "auto":
                d = route(cands, required=req, est_input_tokens=base_in + 1500, est_output_tokens=800, routing=c.get("routing") or {},
                          policy_snapshot=policy, min_context=n.contract.min_context_tokens if n.contract else None)
                if d.model:
                    model = {"provider": d.provider, "model": d.model}
                    est["predicted_model"] = f"{d.provider}/{d.model}"
                    check("Models & capabilities", "pass", f"{n.name or n.key}: AUTO would currently choose {d.provider}/{d.model}", n.id)
                else:
                    check("Models & capabilities", "fail", f"{n.name or n.key}: no configured model satisfies AUTO requirements", n.id)
            elif model.get("provider"):
                pr = pricing_rows.get((model["provider"], model.get("model")))
                gaps = capability_gaps(pr.capabilities if pr else {}, req, n.contract.min_context_tokens if n.contract else None,
                                       pr.context_window if pr else None)
                declared = set(n.contract.capabilities) if n.contract else set()
                # Only capabilities the contract *declares* block the run; inferred ones (from tools/schemas) warn,
                # which keeps V1 workflows runnable.
                hard_gaps = capability_gaps(pr.capabilities if pr else {}, sorted(declared - {"text"}),
                                            n.contract.min_context_tokens if n.contract else None, pr.context_window if pr else None)
                hard = {g for g in hard_gaps if "not supported" in g or "<" in g}
                for g in gaps:
                    check("Models & capabilities", "fail" if g in hard else "warn", f"{n.name or n.key}: {model['model']}: {g}", n.id)
                pol = evaluate_model(policy, model["provider"], model.get("model", ""))
                if pol.effect == "deny":
                    check("Policies", "fail", f"{n.name or n.key}: {pol.reason}", n.id)
            est["model"] = f"{model.get('provider')}/{model.get('model')}"
            for t in tools:
                d = evaluate_tool(policy, t, tool_action(t, {}), {"agent_template": c.get("template"), "node_key": n.key})
                if d.effect == "deny":
                    check("Policies", "warn", f"{n.name or n.key}: tool {t} is denied by policy ({d.reason}); calls will be refused", n.id)
                elif d.effect == "require_approval":
                    approvals_possible += 1
                    check("Policies", "warn", f"{n.name or n.key}: {t} calls will pause for approval ({d.reason})", n.id)
            iters = c.get("max_tool_iterations", 8) if tools else 0
            retries = min((c.get("retry") or {}).get("retries", 0), settings.get("max_retries_per_node", 3))
            est["calls"] = [1, 1 + min(iters, 4) + (2 if structured else 0) + retries]
            out_lo, out_hi = (int(h["out"] * 0.7), int(h["out"] * 1.5)) if h else (250, int((c.get("params") or {}).get("max_tokens") or 1500))
            est["out_tokens"] = [out_lo, out_hi]
            pr = pricing_rows.get((model.get("provider"), model.get("model")))
            est["_pricing"] = {"input_per_mtok": pr.input_per_mtok, "output_per_mtok": pr.output_per_mtok} if pr and pr.input_per_mtok is not None else None
            est["_window"] = pr.context_window if pr else None
            lat = (h["latency_ms"] / 1000) if h else float(((pr.capabilities or {}) if pr else {}).get("latency_s") or 6)
            est["latency_s"] = [round(lat * 0.6, 1), round(lat * est["calls"][1] * 0.8 + lat * 0.4, 1)]
            if h:
                est["source"] = f"history ({h['runs']} runs)"
            if n.harness.cache.mode != "disabled":
                est["cacheable"] = True
        elif n.type.startswith("tool_"):
            est["latency_s"] = [0.3, 8.0] if n.type in ("tool_web_search", "tool_http", "tool_python") else [0.02, 0.5]
            if h:
                est["latency_s"] = [round(h["latency_ms"] / 1000 * 0.6, 2), round(h["latency_ms"] / 1000 * 1.8, 2)]
                est["source"] = f"history ({h['runs']} runs)"
            try:
                args = n.config.get("arguments") or {}
                name = {"tool_http": "http_request", "tool_web_search": "web_search", "tool_python": "python"}.get(n.type, n.type[5:])
                d = evaluate_tool(policy, name, tool_action(name, args), {"node_key": n.key, "args": args})
                if d.effect == "deny":
                    check("Policies", "fail", f"{n.name or n.key}: {d.reason}", n.id)
                elif d.effect == "require_approval":
                    approvals_possible += 1
                    check("Policies", "warn", f"{n.name or n.key}: will pause for approval ({d.reason})", n.id)
            except Exception:
                pass
        elif n.type == "human_approval":
            approvals_possible += 1
            est["durable_wait"] = True
            est["latency_s"] = [0, 0]
        elif n.type in ("wait_timer", "wait_webhook", "wait_event"):
            waits += 1
            est["durable_wait"] = True
            est["latency_s"] = [0, 0]
        elif n.type == "subworkflow":
            est["durable_wait"] = True
            sub = await _subworkflow_plan(db, n, workspace_id, project_id, settings, policy, _depth)
            if sub.get("error"):
                check("Sub-workflows", "fail", f"{n.name or n.key}: {sub['error']}", n.id)
            else:
                check("Sub-workflows", "pass", f"{n.name or n.key}: pinned to v{sub['version']}", n.id)
                t = sub["plan"]["totals"]
                est.update({"calls": t["llm_calls"], "in_tokens": [0, 0], "out_tokens": [t["tokens"][0], t["tokens"][1]],
                            "cost": t["cost_usd"], "latency_s": t["active_seconds"], "source": f"sub-workflow v{sub['version']}"})
                est["_fixed"] = True
        per_node[n.id] = est

    # ---- propagate upstream output sizes into agent input estimates; cost per node
    order = cg.order if cg else list(nodes)
    for nid in order:
        est = per_node.get(nid)
        if not est or est.get("_fixed"):
            continue
        if est["type"] == "agent":
            ups = [per_node[e.source] for e in (cg.incoming.get(nid, []) if cg else []) if e.source in per_node]
            up_lo = sum(u["out_tokens"][0] for u in ups) or 200
            up_hi = sum(u["out_tokens"][1] for u in ups) or 800
            est["in_tokens"] = [est["_base_in"] + up_lo, est["_base_in"] + up_hi]
            h = hist.get(est["key"])
            if h:
                est["in_tokens"] = [int(h["in"] * 0.7), int(h["in"] * 1.5)]
            p = est.get("_pricing")
            lo = estimate_cost(p, est["in_tokens"][0], est["out_tokens"][0]) if p else None
            hi = estimate_cost(p, est["in_tokens"][1] * est["calls"][1], est["out_tokens"][1] * est["calls"][1]) if p else None
            if p is None and not est["model"].startswith(("ollama/", "local_test/")):
                est["unpriced"] = True
            est["cost"] = [round(lo or 0, 6), round(hi or 0, 6)]
            budget_ctx = ((nodes[nid].config.get("context") or {}).get("max_context_tokens"))
            window = est.get("_window")
            if window and est["in_tokens"][1] > window:
                check("Context", "fail" if est["in_tokens"][0] > window else "warn",
                      f"{est['name']}: context may reach ~{est['in_tokens'][1]:,} tokens, above the model window ({window:,})", nid)
            elif budget_ctx and est["in_tokens"][1] > budget_ctx:
                check("Context", "warn", f"{est['name']}: context may exceed the configured budget ({budget_ctx:,}); lower-priority sources will be reduced", nid)

    # ---- loops multiply their bodies
    if cg:
        for loop_id, body in cg.loop_bodies.items():
            mx = min(int(nodes[loop_id].config.get("max_iterations", 10)), settings.get("max_loop_iterations", 10))
            for b in body:
                e = per_node.get(b)
                if e:
                    e["calls"] = [e["calls"][0], e["calls"][1] * mx]
                    e["cost"] = [e["cost"][0], round(e["cost"][1] * mx, 6)]
                    e["latency_s"] = [e["latency_s"][0], round(e["latency_s"][1] * mx, 1)]
                    e["loop_multiplier"] = mx

    # ---- critical path (active time; durable waits excluded)
    def critical(idx: int) -> float:
        best: dict[str, float] = {}
        for nid in order:
            if nid not in per_node:
                continue
            preds = [best.get(e.source, 0) for e in (cg.incoming.get(nid, []) if cg else [])]
            best[nid] = max(preds, default=0) + per_node[nid]["latency_s"][idx]
        return round(max(best.values(), default=0), 1)

    levels: dict[str, int] = {}
    for nid in order:
        preds = [levels.get(e.source, 0) for e in (cg.incoming.get(nid, []) if cg else [])]
        levels[nid] = max(preds, default=-1) + 1
    width = max(defaultdict(int, {l: sum(1 for x in levels.values() if x == l) for l in set(levels.values())}).values(), default=0)

    tot_calls = [sum(e["calls"][i] for e in per_node.values()) for i in (0, 1)]
    tot_tok = [sum(e["in_tokens"][i] * (1 if i == 0 else max(1, e["calls"][1])) + e["out_tokens"][i] * (1 if i == 0 else max(1, e["calls"][1]))
                   for e in per_node.values() if e["type"] == "agent") for i in (0, 1)]
    for e in per_node.values():
        if e.get("_fixed"):
            tot_tok = [tot_tok[0] + e["out_tokens"][0], tot_tok[1] + e["out_tokens"][1]]
    tot_cost = [round(sum(e["cost"][i] for e in per_node.values()), 4) for i in (0, 1)]
    active = [critical(0), critical(1)]
    approvals_possible += len(approval_rules_triggered(policy, {"projected_cost": tot_cost[1], "projected_tokens": tot_tok[1],
                                                                "projected_llm_calls": tot_calls[1]})) and 1 or 0

    # ---- budgets
    mc = settings.get("max_cost")
    if mc is not None:
        if tot_cost[0] > mc:
            check("Budgets", "fail", f"Even the minimum estimate (${tot_cost[0]:.2f}) exceeds the ${mc} cost limit")
        elif tot_cost[1] > mc:
            check("Budgets", "warn", f"Worst case (${tot_cost[1]:.2f}) exceeds the ${mc} limit; the run stops if the limit is reached")
        else:
            check("Budgets", "pass", f"Estimated ${tot_cost[0]:.2f}–${tot_cost[1]:.2f} within the ${mc} limit")
    if tot_calls[0] > settings.get("max_llm_calls", 50):
        check("Budgets", "fail", f"At least {tot_calls[0]} model calls are needed; the limit is {settings.get('max_llm_calls')}")
    elif tot_calls[1] > settings.get("max_llm_calls", 50):
        check("Budgets", "warn", f"Up to {tot_calls[1]} model calls possible; the limit of {settings.get('max_llm_calls')} may stop the run")
    if any(e.get("unpriced") for e in per_node.values()):
        check("Budgets", "warn", "Some models have no price in the pricing table; cost estimates exclude them")
    for cat in CATEGORIES:
        if not any(c["category"] == cat for c in checks):
            check(cat, "pass", "No issues")

    blocked = any(c["status"] == "fail" for c in checks)
    for e in per_node.values():
        for k in [k for k in e if k.startswith("_")]:
            e.pop(k)
    agents = sum(1 for n in nodes.values() if n.type == "agent")
    return {
        "status": "BLOCKED" if blocked else "READY",
        "counts": {"nodes": len(nodes), "agents": agents, "logic": sum(1 for n in nodes.values() if n.type in
                   ("condition", "router", "parallel", "merge", "loop", "retry", "transform")),
                   "tools": sum(1 for n in nodes.values() if n.type.startswith("tool_")), "parallel_branches": width,
                   "human_approvals": approvals_possible, "durable_waits": waits,
                   "subworkflows": sum(1 for n in nodes.values() if n.type == "subworkflow")},
        "totals": {"llm_calls": tot_calls, "tokens": tot_tok, "cost_usd": tot_cost, "active_seconds": active},
        "nodes": list(per_node.values()) if not cg else [dict(per_node[n], node_id=n) for n in order if n in per_node],
        "checks": checks,
        "warnings": [c["message"] for c in checks if c["status"] == "warn"],
        "note": "Estimates use this workflow's recent run history where available, otherwise registry priors. Costs are estimates.",
    }


async def _subworkflow_plan(db, node, workspace_id, project_id, settings, policy, depth) -> dict:
    import uuid
    from isocline.db.models import Workflow
    if depth >= 2:
        return {"error": "nested too deeply to estimate"}
    wid = (node.config or {}).get("workflow_id")
    try:
        wf = await db.get(Workflow, uuid.UUID(str(wid)))
    except (ValueError, TypeError):
        wf = None
    if wf is None:
        return {"error": "sub-workflow not found"}
    q = select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id)
    ver = (node.config or {}).get("version")
    q = q.where(WorkflowVersion.version == ver) if ver else q.order_by(WorkflowVersion.version.desc())
    v = (await db.execute(q.limit(1))).scalar_one_or_none()
    if v is None:
        return {"error": "sub-workflows must reference a published version"}
    g = WorkflowGraph.model_validate(v.graph)
    plan = await build_plan(db, g, workflow_id=wf.id, workspace_id=workspace_id, project_id=project_id, settings=settings,
                            policy=policy, _depth=depth + 1)
    return {"version": v.version, "plan": plan}
