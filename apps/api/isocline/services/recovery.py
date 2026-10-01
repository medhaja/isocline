"""Queue recovery used by the stale-run sweeper: runs that never started executing (queued, or
resuming after a wait) are re-enqueued from PostgreSQL. Claiming is atomic, so duplicates are harmless."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import Run, utcnow


async def requeue_pending(db: AsyncSession, stale_seconds: int = 60, enqueue: bool = True) -> list[str]:
    cutoff = utcnow() - timedelta(seconds=stale_seconds)
    rows = (await db.execute(select(Run).where(Run.status.in_(["queued", "resuming"]),
                                               Run.heartbeat_at.is_(None) | (Run.heartbeat_at < cutoff),
                                               Run.created_at < cutoff))).scalars().all()
    ids = [str(r.id) for r in rows]
    if enqueue:
        from isocline.services.dispatch import enqueue_run
        for i in ids:
            enqueue_run(i)
    return ids
