"""What Celery workers and Celery beat do on the server, inside the desktop app's own event loop.

* Runs, ingestion and evaluations are executed by isocline.services.dispatch (in-process, bounded concurrency).
* This module recovers work interrupted when the app was last closed, and runs the periodic jobs Beat runs:
  durable waits (5 s), schedule triggers (20 s), the stale-run sweeper (30 s) and drift detection (1 h).

Durability is unchanged: all state lives in the database, so closing the app mid-run loses nothing. A run that was
executing is resumed on the next start from its completed nodes (at-least-once per node, as on the server)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, update

from isocline.core.config import get_settings
from isocline.core.logging import log
from isocline.db import session as dbs
from isocline.db.models import Document, Run, utcnow

MAX_RECOVERY_ATTEMPTS = 3


async def _fail_exhausted(db, run: Run) -> None:
    from isocline.engine.events import NullBus
    from isocline.engine.store import SqlRunStore
    run.status = "failed"
    run.finished_at = utcnow()
    run.error = {"code": "worker_lost",
                 "message": "This run was interrupted repeatedly (the app closed or crashed) and recovery attempts were exhausted"}
    await db.commit()
    await SqlRunStore(NullBus()).emit(str(run.id), "RUN_FAILED", {"status": "failed", "error": run.error})


async def recover_on_startup() -> int:
    """Everything left RUNNING belongs to a previous process of this app: there is no other worker. Clear its heartbeat
    so it can be claimed immediately (instead of after worker_stale_seconds), and re-enqueue it together with queued
    runs and unfinished document ingestions."""
    from isocline.services.dispatch import enqueue_ingest, enqueue_run
    n = 0
    async with dbs.sessionmaker()() as db:
        interrupted = (await db.execute(select(Run).where(Run.status == "running"))).scalars().all()
        for run in interrupted:
            if run.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
                await _fail_exhausted(db, run)
                continue
            run.recovery_attempts += 1
            run.heartbeat_at = None
            await db.commit()
            log.warning("run_recovery", run_id=str(run.id), attempt=run.recovery_attempts, reason="app_restart")
            enqueue_run(str(run.id))
            n += 1
        pending = (await db.execute(select(Run.id).where(Run.status.in_(["queued", "resuming"])))).scalars().all()
        for rid in pending:
            enqueue_run(str(rid))
            n += 1
        # Ingestion has no heartbeat; on a single-process install, "processing" at startup means it was interrupted.
        await db.execute(update(Document).where(Document.status == "processing").values(status="pending"))
        await db.commit()
        for did in (await db.execute(select(Document.id).where(Document.status == "pending"))).scalars().all():
            enqueue_ingest(str(did))
            n += 1
    if n:
        log.info("desktop_recovered_work", items=n)
    return n


async def sweep_stale_runs() -> int:
    """Same policy as the server sweeper (isocline.worker.tasks.sweep_stale_runs), dispatching in-process."""
    from isocline.services.dispatch import enqueue_run, inflight
    from isocline.services.recovery import requeue_pending
    s = get_settings()
    n = 0
    cutoff = utcnow() - timedelta(seconds=s.worker_stale_seconds)
    async with dbs.sessionmaker()() as db:
        stale = (await db.execute(select(Run).where(Run.status == "running", Run.heartbeat_at < cutoff))).scalars().all()
        n += len(await requeue_pending(db, s.worker_stale_seconds))
        busy = inflight()
        for run in stale:
            if f"run:{run.id}" in busy:
                continue  # still executing here; a missed heartbeat (e.g. the PC slept) is not a crash
            n += 1
            if run.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
                await _fail_exhausted(db, run)
            else:
                run.recovery_attempts += 1
                await db.commit()
                log.warning("run_recovery", run_id=str(run.id), attempt=run.recovery_attempts)
                enqueue_run(str(run.id))
    return n


async def _job(name: str, fn) -> None:
    try:
        async with dbs.sessionmaker()() as db:
            await fn(db)
    except Exception as e:  # one failing job must never stop the scheduler
        log.warning("desktop_job_failed", job=name, error=str(e))


async def scheduler() -> None:
    from isocline.services.monitoring import detect_all_drift
    from isocline.services.triggers import fire_due_schedules
    from isocline.services.waits import process_due_waits

    try:
        await recover_on_startup()
    except Exception as e:
        log.error("desktop_recovery_failed", error=str(e))
    tick = 0  # 5-second ticks
    while True:
        await _job("process_waits", process_due_waits)
        if tick % 4 == 0:
            await _job("fire_schedules", fire_due_schedules)
        if tick % 6 == 5:
            try:
                await sweep_stale_runs()
            except Exception as e:
                log.warning("desktop_job_failed", job="sweep_stale_runs", error=str(e))
        if tick % 720 == 719:
            await _job("detect_drift", detect_all_drift)
        tick += 1
        await asyncio.sleep(5)
