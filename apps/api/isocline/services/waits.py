"""Durable waits are resumed from the database, never by a sleeping worker:
  * process_due_waits(): timers that are due and waits past their timeout (run by beat every few seconds)
  * resolve_callback(): webhook callbacks (HMAC capability URL)
  * publish_event(): external events matched by name + correlation key
Resuming marks the wait, sets the run to 'resuming' and enqueues it; the executor reuses completed node outputs."""
from __future__ import annotations

import hmac
import uuid
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import Approval, Run, utcnow
from isocline.db.models_v2 import WaitState
from isocline.services.dispatch import enqueue_run


async def _wake(db: AsyncSession, run_id) -> bool:
    res = await db.execute(update(Run).where(Run.id == run_id, Run.status == "waiting").values(status="resuming", heartbeat_at=utcnow()))
    return res.rowcount == 1


async def process_due_waits(db: AsyncSession) -> dict:
    now = utcnow()
    woke: set = set()
    timers = (await db.execute(select(WaitState).where(WaitState.status == "waiting", WaitState.kind == "timer",
                                                       WaitState.resume_at <= now).limit(500))).scalars().all()
    for w in timers:
        w.status, w.resolved_at, w.payload = "resumed", now, {"resumed_at": now.isoformat()}
        woke.add(w.run_id)
    expired = (await db.execute(select(WaitState).where(WaitState.status == "waiting", WaitState.timeout_at.is_not(None),
                                                        WaitState.timeout_at <= now).limit(500))).scalars().all()
    for w in expired:
        w.status, w.resolved_at = "timed_out", now
        if w.kind == "approval":
            await db.execute(update(Approval).where(Approval.run_id == w.run_id, Approval.node_id == w.node_id,
                                                    Approval.scope == w.scope, Approval.status == "pending").values(status="expired", decided_at=now))
        woke.add(w.run_id)
    resumed = [rid for rid in woke if await _wake(db, rid)]
    await db.commit()
    for rid in resumed:
        enqueue_run(str(rid))
    return {"timers": len(timers), "timeouts": len(expired), "runs_resumed": len(resumed)}


def verify_callback(run_id: str, node_id: str, token: str) -> bool:
    from isocline.engine.executor import callback_token
    return hmac.compare_digest(callback_token(run_id, node_id), token)


async def resolve_callback(db: AsyncSession, run_id: str, node_id: str, payload: Any) -> str:
    """Returns 'resumed' | 'early' (callback before the run reached the wait) | 'duplicate' | 'gone'."""
    run = await db.get(Run, uuid.UUID(run_id))
    if run is None or run.status in ("completed", "failed", "cancelled"):
        return "gone"
    w = (await db.execute(select(WaitState).where(WaitState.run_id == run.id, WaitState.node_id == node_id, WaitState.scope == ""))).scalar_one_or_none()
    if w is None:  # arrived early: record it; the wait node completes immediately when reached
        db.add(WaitState(run_id=run.id, workspace_id=run.workspace_id, node_id=node_id, scope="", kind="webhook", status="resumed",
                         payload=payload, resolved_at=utcnow()))
        await db.commit()
        return "early"
    if w.status != "waiting":
        return "duplicate"
    # Atomic claim: concurrent deliveries race on this conditional UPDATE; exactly one wins (SQLite and PostgreSQL).
    res = await db.execute(update(WaitState).where(WaitState.id == w.id, WaitState.status == "waiting")
                           .values(status="resumed", payload=payload, resolved_at=utcnow()))
    if res.rowcount != 1:
        await db.rollback()
        return "duplicate"
    woke = await _wake(db, run.id)
    await db.commit()
    if woke:
        enqueue_run(str(run.id))
    return "resumed"


async def publish_event(db: AsyncSession, workspace_id, name: str, correlation_key: str | None, payload: Any) -> dict:
    q = select(WaitState).where(WaitState.workspace_id == workspace_id, WaitState.status == "waiting", WaitState.kind == "event",
                                WaitState.event_name == name)
    if correlation_key:
        q = q.where(or_(WaitState.correlation_key == correlation_key, WaitState.correlation_key.is_(None)))
    else:
        q = q.where(WaitState.correlation_key.is_(None))
    waits = (await db.execute(q.limit(1000))).scalars().all()
    runs = set()
    claimed = 0
    for w in waits:
        res = await db.execute(update(WaitState).where(WaitState.id == w.id, WaitState.status == "waiting").values(
            status="resumed", payload={"event": name, "correlation_key": correlation_key, "payload": payload}, resolved_at=utcnow()))
        if res.rowcount == 1:  # a concurrent publisher may have claimed it first
            claimed += 1
            runs.add(w.run_id)
    resumed = [r for r in runs if await _wake(db, r)]
    await db.commit()
    for r in resumed:
        enqueue_run(str(r))
    return {"waits_resumed": claimed, "runs_resumed": len(resumed)}
