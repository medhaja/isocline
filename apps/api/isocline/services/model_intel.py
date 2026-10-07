"""Model capability registry access and measured model metrics for routing."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.config import get_settings
from isocline.db.models import ModelPricing, NodeRun, ProviderCredential, Run, utcnow
from isocline.db.models_v2 import ExperimentVariant
from isocline.engine.router import Candidate
from isocline.providers.registry import provider_classes


async def model_metrics(db: AsyncSession, workspace_id) -> dict[tuple[str, str], dict]:
    """Per provider/model: 7-day success rate and latency, 1-hour error rate, and experiment-measured quality."""
    now = utcnow()
    week = (await db.execute(
        select(NodeRun.provider, NodeRun.model, func.count(NodeRun.id),
               func.sum(case((NodeRun.status == "failed", 1), else_=0)), func.avg(NodeRun.latency_ms))
        .join(Run, Run.id == NodeRun.run_id)
        .where(Run.workspace_id == workspace_id, NodeRun.node_type == "agent", NodeRun.provider.is_not(None),
               NodeRun.started_at >= now - timedelta(days=7), NodeRun.cache_status.is_distinct_from("hit"))
        .group_by(NodeRun.provider, NodeRun.model))).all()
    hour = (await db.execute(
        select(NodeRun.provider, NodeRun.model, func.count(NodeRun.id), func.sum(case((NodeRun.status == "failed", 1), else_=0)))
        .join(Run, Run.id == NodeRun.run_id)
        .where(Run.workspace_id == workspace_id, NodeRun.node_type == "agent", NodeRun.provider.is_not(None),
               NodeRun.started_at >= now - timedelta(hours=1))
        .group_by(NodeRun.provider, NodeRun.model))).all()
    out: dict[tuple[str, str], dict] = {}
    for p, m, n, f, lat in week:
        out[(p, m)] = {"calls": n, "success_rate": round(1 - (f or 0) / n, 4) if n else None,
                       "p50_latency_ms": int(lat) if lat else None}
    for p, m, n, f in hour:
        out.setdefault((p, m), {}).update({"recent_calls": n, "recent_error_rate": round((f or 0) / n, 4) if n else 0})
    # quality measured by experiments (variant pass rate on a dataset) — the only source treated as "evaluation score"
    variants = (await db.execute(select(ExperimentVariant.overrides, ExperimentVariant.metrics).where(ExperimentVariant.metrics != None))).all()  # noqa: E711
    agg: dict[tuple[str, str], list[float]] = {}
    for ov, met in variants:
        model = (ov or {}).get("model") or {}
        if model.get("provider") and model.get("model") and isinstance((met or {}).get("pass_rate"), (int, float)):
            agg.setdefault((model["provider"], model["model"]), []).append(float(met["pass_rate"]))
    for k, vals in agg.items():
        out.setdefault(k, {})["eval_score"] = round(sum(vals) / len(vals), 4)
    return out


async def load_candidates(db: AsyncSession, workspace_id) -> list[Candidate]:
    classes = provider_classes()
    creds = {p for p in (await db.execute(select(ProviderCredential.provider).where(ProviderCredential.workspace_id == workspace_id))).scalars()}
    metrics = await model_metrics(db, workspace_id)
    rows = (await db.execute(select(ModelPricing).where(ModelPricing.active == True))).scalars().all()  # noqa: E712
    out = []
    for r in rows:
        cls = classes.get(r.provider)
        if cls is None:
            continue
        has = r.provider in creds or (r.provider == "local_test" and get_settings().enable_test_provider)
        pricing = None
        if r.input_per_mtok is not None:
            pricing = {"input_per_mtok": r.input_per_mtok, "output_per_mtok": r.output_per_mtok, "cached_input_per_mtok": r.cached_input_per_mtok}
        out.append(Candidate(r.provider, r.model, dict(r.capabilities or {}), r.context_window, pricing, has,
                             metrics.get((r.provider, r.model), {}), curated=(r.source or "catalog") != "feed"))
    return out


async def capability_table(db: AsyncSession, workspace_id) -> list[dict]:
    cands = await load_candidates(db, workspace_id)
    return [{"provider": c.provider, "model": c.model, "context_window": c.context_window, "capabilities": c.capabilities,
             "pricing": c.pricing, "configured": c.has_credential, "metrics": c.metrics} for c in cands]
