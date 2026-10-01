"""Monitoring: metrics, drift detection, execution heatmaps, bottlenecks and lineage.

Drift compares the last 24 hours against a *baseline*: the first 7 days after the current version was released
Only metrics Isocline actually measures are compared; "evaluation proxy" drift is output-size drift
and is labelled as a proxy. Lineage reports provenance that was recorded (edges actually taken, templates that
reference upstream fields, artifacts, retrieved documents, tool sources) and never invents it."""
from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import Approval, NodeRun, Run, ToolRun, Workflow, WorkflowVersion, utcnow
from isocline.db.models_v2 import (
    Artifact, ArtifactUsage, DriftEvent, ModelRoutingDecision,
)

DRIFT_RULES = {  # metric: (relative increase, absolute floor, severity)
    "cost_per_run": (0.30, 0.001, "warning"),
    "latency_p95_s": (0.50, 1.0, "warning"),
    "failure_rate": (1.0, 0.05, "critical"),
    "schema_failure_rate": (1.0, 0.03, "critical"),
    "tool_error_rate": (1.0, 0.05, "warning"),
    "fallback_rate": (1.0, 0.05, "info"),
    "output_size_tokens": (0.50, 50, "info"),
}


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


async def run_metrics(db: AsyncSession, *, workflow_id=None, version_id=None,
                      since: datetime, until: datetime | None = None, bucket_hours: int = 0) -> dict:
    q = select(Run).where(Run.created_at >= since, Run.trigger.notin_(("eval", "playground")))
    if until:
        q = q.where(Run.created_at < until)
    if workflow_id:
        q = q.where(Run.workflow_id == workflow_id)
    if version_id:
        q = q.where(Run.workflow_version_id == version_id)
    runs = (await db.execute(q.limit(20000))).scalars().all()
    ids = [r.id for r in runs]
    nodes = (await db.execute(select(NodeRun).where(NodeRun.run_id.in_(ids)))).scalars().all() if ids else []
    tools = (await db.execute(select(ToolRun.success).where(ToolRun.run_id.in_(ids)))).all() if ids else []
    approvals = (await db.execute(select(Approval.run_id).where(Approval.run_id.in_(ids)))).scalars().all() if ids else []
    routes = (await db.execute(select(ModelRoutingDecision.selected_provider, ModelRoutingDecision.selected_model)
                               .where(ModelRoutingDecision.run_id.in_(ids)))).all() if ids else []
    done = [r for r in runs if r.status in ("completed", "failed", "cancelled")]
    lat = [(_aware(r.finished_at) - _aware(r.started_at)).total_seconds() for r in done if r.finished_at and r.started_at]
    agents = [n for n in nodes if n.node_type == "agent" and n.status in ("completed", "failed")]
    schema_fail = [n for n in agents if n.status == "failed" and (n.error or {}).get("kind") in ("structured_output", "contract_violation")]
    cache_eligible = [n for n in nodes if n.cache_status in ("hit", "stored", "miss")]
    m = {
        "requests": len(runs), "completed": sum(1 for r in runs if r.status == "completed"),
        "failed": sum(1 for r in runs if r.status == "failed"), "waiting": sum(1 for r in runs if r.status == "waiting"),
        "success_rate": round(sum(1 for r in done if r.status == "completed") / len(done), 4) if done else None,
        "failure_rate": round(sum(1 for r in done if r.status == "failed") / len(done), 4) if done else None,
        "latency_p50_s": round(median(lat), 2) if lat else None, "latency_p95_s": round(_pct(lat, 0.95), 2) if lat else None,
        "cost_total": round(sum(r.cost_usd or 0 for r in runs), 4),
        "cost_per_run": round(sum(r.cost_usd or 0 for r in done) / len(done), 5) if done else None,
        "tokens": sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in runs),
        "tool_calls": len(tools), "tool_error_rate": round(sum(1 for (ok,) in tools if not ok) / len(tools), 4) if tools else None,
        "provider_errors": sum(1 for n in agents for a in (n.attempts or []) if isinstance(a, dict) and a.get("error_kind")),
        "fallback_rate": round(sum(1 for n in agents if n.fallback_used) / len(agents), 4) if agents else None,
        "schema_failure_rate": round(len(schema_fail) / len(agents), 4) if agents else None,
        "cache_hit_rate": round(sum(1 for n in cache_eligible if n.cache_status == "hit") / len(cache_eligible), 4) if cache_eligible else None,
        "cache_savings_usd": round(sum(n.saved_cost_usd or 0 for n in nodes if n.cache_status == "hit"), 4),
        "approval_rate": round(len(set(approvals)) / len(runs), 4) if runs else None,
        "output_size_tokens": round(sum(n.output_tokens or 0 for n in agents) / len(agents), 1) if agents else None,
        "routing": [{"model": f"{p}/{m_}", "count": c} for (p, m_), c in Counter(routes).most_common(8)],
        "cost_is_estimate": True,
    }
    if bucket_hours:
        buckets: dict[str, dict] = defaultdict(lambda: {"requests": 0, "failed": 0, "cost": 0.0, "lat": []})
        for r in runs:
            t = _aware(r.created_at)
            key = t.replace(minute=0, second=0, microsecond=0) - timedelta(hours=t.hour % bucket_hours)
            b = buckets[key.isoformat()]
            b["requests"] += 1
            b["failed"] += r.status == "failed"
            b["cost"] += r.cost_usd or 0
            if r.finished_at and r.started_at:
                b["lat"].append((_aware(r.finished_at) - _aware(r.started_at)).total_seconds())
        m["series"] = [{"t": k, "requests": v["requests"], "failed": v["failed"], "cost": round(v["cost"], 4),
                        "latency_p95_s": round(_pct(v["lat"], 0.95), 2) if v["lat"] else None} for k, v in sorted(buckets.items())]
    return m


async def node_breakdown(db: AsyncSession, run_ids: list) -> dict[str, dict]:
    if not run_ids:
        return {}
    rows = (await db.execute(select(NodeRun).where(NodeRun.run_id.in_(run_ids)))).scalars().all()
    agg: dict[str, dict] = defaultdict(lambda: {"runs": 0, "cost": 0.0, "tokens": 0, "latency": [], "errors": 0, "retries": 0,
                                                "fallbacks": 0, "cache_hits": 0, "context": 0})
    for n in rows:
        a = agg[n.node_id]
        a["key"], a["type"] = n.node_key, n.node_type
        a["runs"] += 1
        a["cost"] += n.cost_usd or 0
        a["tokens"] += (n.input_tokens or 0) + (n.output_tokens or 0)
        # durable waits (approvals, timers, callbacks, sub-workflows) are not active execution time
        if n.latency_ms is not None and n.status in ("completed", "failed") and n.node_type not in (
                "human_approval", "wait_timer", "wait_webhook", "wait_event", "subworkflow"):
            a["latency"].append(n.latency_ms)
        a["errors"] += n.status == "failed"
        a["retries"] += sum(1 for x in (n.attempts or []) if isinstance(x, dict) and x.get("status") == "failed")
        a["fallbacks"] += bool(n.fallback_used)
        a["cache_hits"] += n.cache_status == "hit"
        a["context"] = max(a["context"], int((n.input or {}).get("context_total_tokens") or 0) if isinstance(n.input, dict) else 0)
    out = {}
    for nid, a in agg.items():
        runs = max(1, a["runs"])
        out[nid] = {"key": a.get("key"), "type": a.get("type"), "runs": a["runs"], "cost": round(a["cost"] / runs, 6),
                    "tokens": int(a["tokens"] / runs), "latency_ms": int(median(a["latency"])) if a["latency"] else None,
                    "errors": a["errors"], "error_rate": round(a["errors"] / runs, 4), "retries": a["retries"],
                    "fallbacks": a["fallbacks"], "cache_hits": a["cache_hits"], "cache_hit_rate": round(a["cache_hits"] / runs, 4),
                    "max_context_tokens": a["context"]}
    return out


async def heatmap(db: AsyncSession, workflow_id, run_id=None, last: int = 20) -> dict:
    if run_id:
        ids = [uuid.UUID(str(run_id))]
    else:
        ids = (await db.execute(select(Run.id).where(Run.workflow_id == workflow_id, Run.status.in_(("completed", "failed")),
                                                     Run.trigger != "playground").order_by(Run.created_at.desc()).limit(last))).scalars().all()
    nodes = await node_breakdown(db, list(ids))
    from isocline.db.models_v2 import ComponentTest
    tests = (await db.execute(select(ComponentTest).where(ComponentTest.workflow_id == workflow_id))).scalars().all()
    ev: dict[str, list] = defaultdict(list)
    for t in tests:
        if t.last_status in ("passed", "failed"):
            ev[t.node_id].append(1.0 if t.last_status == "passed" else 0.0)
    for nid, vals in ev.items():
        nodes.setdefault(nid, {"runs": 0})["evaluation"] = round(sum(vals) / len(vals), 3)

    def top(metric: str, label: str, fmt=str):
        cands = [(nid, v) for nid, v in nodes.items() if v.get(metric)]
        if not cands:
            return None
        nid, v = max(cands, key=lambda x: x[1][metric])
        return {"node_id": nid, "key": v.get("key"), "metric": metric, "label": label, "value": v[metric]}
    lowest_eval = min(((nid, v) for nid, v in nodes.items() if v.get("evaluation") is not None), key=lambda x: x[1]["evaluation"], default=None)
    bottlenecks = [b for b in [top("cost", "Highest cost"), top("latency_ms", "Highest latency"), top("max_context_tokens", "Largest context"),
                               top("retries", "Most retries"), top("errors", "Most failures"), top("fallbacks", "Most fallback usage")] if b]
    if lowest_eval:
        bottlenecks.append({"node_id": lowest_eval[0], "key": lowest_eval[1].get("key"), "metric": "evaluation",
                            "label": "Lowest component-test pass rate", "value": lowest_eval[1]["evaluation"]})
    return {"runs_analyzed": len(ids), "nodes": nodes, "bottlenecks": bottlenecks,
            "modes": ["cost", "latency_ms", "tokens", "errors", "cache_hit_rate", "evaluation"]}


# ------------------------------------------------------------------------------------------ drift
async def baseline_window(db: AsyncSession, workflow_id, now: datetime | None = None) -> tuple[datetime, datetime, Any] | None:
    """Baseline = the 7 days after the latest published version (or, if never published, the week before the last 24h)."""
    now = now or utcnow()
    v = (await db.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
                          .order_by(WorkflowVersion.version.desc()).limit(1))).scalar_one_or_none()
    if v is not None:
        start = _aware(v.created_at)
        return start, start + timedelta(days=7), v.id
    start = now - timedelta(days=8)
    return start, start + timedelta(days=7), None


async def detect_drift(db: AsyncSession, workflow_id, *, now: datetime | None = None) -> list[DriftEvent]:
    now = now or utcnow()
    win = await baseline_window(db, workflow_id, now)
    if win is None:
        return []
    b_start, b_end, version = win
    recent_start = now - timedelta(hours=24)
    if b_end > recent_start:
        b_end = recent_start  # baseline must not overlap the comparison window
    if b_end <= b_start:
        return []
    kw = {"workflow_id": workflow_id}
    base = await run_metrics(db, since=b_start, until=b_end, **kw)
    cur = await run_metrics(db, since=recent_start, **kw)
    if (base["requests"] or 0) < 5 or (cur["requests"] or 0) < 5:
        return []
    wf = await db.get(Workflow, workflow_id)
    from isocline.db.models import Project
    project = await db.get(Project, wf.project_id)
    day = now.strftime("%Y-%m-%d")
    existing = {(e.metric) for e in (await db.execute(select(DriftEvent).where(DriftEvent.workflow_id == workflow_id, DriftEvent.day == day))).scalars()}
    events = []
    breakdown = None
    for metric, (rel, floor, sev) in DRIFT_RULES.items():
        b, c = base.get(metric), cur.get(metric)
        if b is None or c is None or metric in existing:
            continue
        if c - b > floor and (b == 0 or (c - b) / b > rel):
            if breakdown is None:
                ids = (await db.execute(select(Run.id).where(Run.workflow_id == workflow_id, Run.created_at >= recent_start))).scalars().all()
                breakdown = await node_breakdown(db, list(ids))
            key_metric = {"cost_per_run": "cost", "latency_p95_s": "latency_ms", "failure_rate": "errors", "schema_failure_rate": "errors",
                          "tool_error_rate": "errors", "fallback_rate": "fallbacks", "output_size_tokens": "tokens"}[metric]
            primary = max(breakdown.values(), key=lambda v: v.get(key_metric) or 0, default=None) if breakdown else None
            label = metric.replace("_", " ") + (" (evaluation proxy)" if metric == "output_size_tokens" else "")
            fmt = (lambda x: f"{x:.1%}") if "rate" in metric else (lambda x: f"{x:g}")
            ev = DriftEvent(workspace_id=project.workspace_id, workflow_id=workflow_id,
                            version_id=version, metric=metric, severity=sev, baseline=b, current=c,
                            message=f"{label.capitalize()} changed from {fmt(b)} (baseline) to {fmt(c)} (last 24h)",
                            primary_node_key=primary.get("key") if primary else None, day=day)
            db.add(ev)
            events.append(ev)
    # routing drift: the most used AUTO model changed
    if base["routing"] and cur["routing"] and base["routing"][0]["model"] != cur["routing"][0]["model"] and "routing" not in existing:
        ev = DriftEvent(workspace_id=project.workspace_id, workflow_id=workflow_id,
                        version_id=version, metric="routing", severity="info", baseline=None, current=None, day=day,
                        message=f"AUTO routing now mostly selects {cur['routing'][0]['model']} (baseline: {base['routing'][0]['model']})")
        db.add(ev)
        events.append(ev)
    await db.commit()
    return events


async def detect_all_drift(db: AsyncSession) -> int:
    """Hourly (beat): every workflow that ran in the last 24 hours."""
    since = utcnow() - timedelta(hours=24)
    ids = (await db.execute(select(Run.workflow_id).where(Run.created_at >= since).distinct())).scalars().all()
    n = 0
    for wid in ids:
        n += len(await detect_drift(db, wid))
    return n



# ------------------------------------------------------------------------------------------ lineage
_REF = re.compile(r"\{\{\s*([a-zA-Z_]\w*)(?:\.output)?((?:\.[\w\-]+|\[\d+\])*)\s*\}\}")


async def run_lineage(db: AsyncSession, run: Run, field_path: str | None = None) -> dict:
    """Backward trace from the final outputs through the nodes that actually executed."""
    nodes = {n["id"]: n for n in (run.graph_snapshot or {}).get("nodes", [])}
    key_to_id = {n["key"]: n["id"] for n in nodes.values()}
    nrs = {nr.node_id: nr for nr in (await db.execute(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.scope == ""))).scalars()}
    taken = [e for e in (run.graph_snapshot or {}).get("edges", [])
             if e["source"] in nrs and e["target"] in nrs and nrs[e["source"]].status == "completed" and nrs[e["target"]].status == "completed"
             and (nrs[e["source"]].handle is None or e.get("source_handle") in (None, nrs[e["source"]].handle))]
    arts = (await db.execute(select(Artifact).where(Artifact.run_id == run.id))).scalars().all()
    used = (await db.execute(select(ArtifactUsage).where(ArtifactUsage.run_id == run.id))).scalars().all()
    tools = (await db.execute(select(ToolRun).where(ToolRun.run_id == run.id))).scalars().all()
    nr_by_id = {str(v.id): k for k, v in nrs.items()}
    graph_nodes = []
    for nid, nr in nrs.items():
        n = nodes.get(nid, {})
        sources = []
        inp = nr.input if isinstance(nr.input, dict) else {}
        for h in inp.get("retrieved_knowledge") or []:
            sources.append({"kind": "knowledge", "label": f"{h.get('source')} #{h.get('chunk')}"})
        for t in tools:
            if nr_by_id.get(str(t.node_run_id)) == nid and t.success and t.tool == "web_search":
                for r in (t.output or {}).get("results", [])[:8]:
                    sources.append({"kind": "web", "label": r.get("title") or r.get("url"), "url": r.get("url")})
        graph_nodes.append({"node_id": nid, "key": nr.node_key, "name": n.get("name") or nr.node_key, "type": nr.node_type,
                            "status": nr.status, "model": f"{nr.provider}/{nr.model}" if nr.model else None,
                            "artifacts_produced": [{"id": str(a.id), "name": a.name, "type": a.kind} for a in arts if a.node_id == nid],
                            "artifacts_consumed": list({str(u.artifact_id) for u in used if u.node_id == nid}), "sources": sources})
    field = None
    if field_path:
        field = _trace_field(field_path, nodes, key_to_id, nrs, taken)
    return {"nodes": graph_nodes, "edges": [{"source": e["source"], "target": e["target"]} for e in taken], "field": field,
            "note": "Lineage shows recorded provenance only: executed edges, template references, artifacts, retrieved passages and tool sources."}


def _trace_field(path: str, nodes: dict, key_to_id: dict, nrs: dict, taken: list) -> dict:
    """For a field of the final output, find the node that produced it — exactly when an output template maps it,
    otherwise the producing node and its recorded inputs (never a guessed sentence-level source)."""
    head = path.split(".")[0]
    outputs = [n for n in nodes.values() if n["type"].startswith("output_") and n["id"] in nrs]
    chain = []
    for o in outputs:
        tpl = (o.get("config") or {}).get("template") or ""
        for m in _REF.finditer(tpl):
            src, sub = m.group(1), (m.group(2) or "").lstrip(".")
            if src in key_to_id and (not sub or sub.split(".")[0] == head or head == src):
                chain.append({"node_key": src, "path": sub or None, "via": f"{o['key']} template"})
        if not chain:
            ups = [e["source"] for e in taken if e["target"] == o["id"]]
            for u in ups:
                chain.append({"node_key": nodes[u]["key"], "path": path, "via": "passed through"})
    exact = any(c["via"].endswith("template") for c in chain)
    producer = chain[0]["node_key"] if chain else None
    upstream = []
    if producer:
        pid = key_to_id[producer]
        frontier = [pid]
        seen = set()
        while frontier:
            x = frontier.pop()
            for e in taken:
                if e["target"] == x and e["source"] not in seen:
                    seen.add(e["source"])
                    upstream.append(nodes[e["source"]]["key"])
                    frontier.append(e["source"])
    return {"field": path, "produced_by": producer, "mapping": chain, "based_on": upstream,
            "precision": "exact field mapping" if exact else "node-level (the producing agent's inputs)"}
