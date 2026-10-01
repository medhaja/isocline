"""Tenant quotas and fair scheduling helpers."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError
from isocline.db.models import Run, UsageRecord, utcnow
from isocline.db.models_v2 import WorkspaceQuota


async def get_quota(db: AsyncSession, workspace_id) -> WorkspaceQuota:
    q = await db.get(WorkspaceQuota, workspace_id)
    if q is None:
        q = WorkspaceQuota(workspace_id=workspace_id, max_concurrent_runs=10, max_concurrent_nodes=20, sandbox_concurrency=4,
                           artifact_storage_bytes=5 * 1024 ** 3, rate_limit_per_minute=600)
    return q


async def month_usage(db: AsyncSession, workspace_id) -> tuple[int, float]:
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    t, c = (await db.execute(select(func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0),
                                    func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
                             .where(UsageRecord.workspace_id == workspace_id, UsageRecord.created_at >= start))).one()
    return int(t or 0), float(c or 0)


async def enforce_monthly(db: AsyncSession, workspace_id) -> None:
    q = await get_quota(db, workspace_id)
    if q.monthly_token_quota is None and q.monthly_cost_quota is None:
        return
    tokens, cost = await month_usage(db, workspace_id)
    if q.monthly_token_quota is not None and tokens >= q.monthly_token_quota:
        raise AppError(429, "quota_exceeded", f"This workspace used its monthly token quota ({q.monthly_token_quota:,}).")
    if q.monthly_cost_quota is not None and cost >= q.monthly_cost_quota:
        raise AppError(429, "quota_exceeded", f"This workspace reached its monthly cost quota (${q.monthly_cost_quota:.2f}).")


async def running_count(db: AsyncSession, workspace_id, stale_seconds: int = 60) -> int:
    fresh = utcnow() - timedelta(seconds=stale_seconds)
    return (await db.execute(select(func.count(Run.id)).where(Run.workspace_id == workspace_id, Run.status == "running",
                                                              Run.heartbeat_at >= fresh))).scalar() or 0


async def should_defer(db: AsyncSession, run: Run, stale_seconds: int = 60) -> bool:
    """Fair scheduling: a queued run whose workspace is at its concurrent-run quota waits (re-queued with backoff)."""
    if run.status != "queued":
        return False
    q = await get_quota(db, run.workspace_id)
    return await running_count(db, run.workspace_id, stale_seconds) >= q.max_concurrent_runs
