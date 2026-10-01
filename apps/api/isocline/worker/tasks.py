"""Celery tasks. Each task runs its own event loop with a NullPool DB engine."""
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import timedelta

from sqlalchemy import select

from isocline.core.config import get_settings
from isocline.core.logging import configure_logging, log
from isocline.db import session as dbs
from isocline.db.models import Document, Run, utcnow
from isocline.engine.events import RedisBus
from isocline.engine.executor import Executor
from isocline.engine.store import SqlRunStore

from .celery_app import celery

configure_logging()
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


def _run(coro):
    dbs.configure(worker=True)
    return asyncio.run(coro)


@celery.task(name="isocline.worker.tasks.execute_run", bind=True, max_retries=None)
def execute_run(self, run_id: str) -> str:
    """Fair scheduling: a workspace at its concurrent-run quota is deferred (re-queued with backoff) instead of
    occupying a worker, so one tenant cannot exhaust the shared pool."""
    async def go():
        from isocline.services.quotas import should_defer
        async with dbs.sessionmaker()() as db:
            run = await db.get(Run, uuid.UUID(run_id))
            if run is None:
                return "missing"
            if await should_defer(db, run, get_settings().worker_stale_seconds):
                return "throttled"
        store = SqlRunStore(RedisBus(get_settings().redis_url))
        return await Executor(store, run_id, f"{WORKER_ID}-{uuid.uuid4().hex[:6]}").execute()
    status = _run(go())
    if status == "throttled":
        n = self.request.retries or 0
        log.info("run_throttled_by_quota", run_id=run_id, attempt=n)
        raise self.retry(countdown=min(60, 2 + 2 * n))
    log.info("run_finished", run_id=run_id, status=status)
    return status


@celery.task(name="isocline.worker.tasks.process_waits")
def process_waits() -> dict:
    """Resumes due timers and expired waits. Durable waits hold no worker; this is how they wake up."""
    from isocline.services.waits import process_due_waits

    async def go():
        async with dbs.sessionmaker()() as db:
            return await process_due_waits(db)
    return _run(go())


@celery.task(name="isocline.worker.tasks.fire_schedules")
def fire_schedules() -> int:
    from isocline.services.triggers import fire_due_schedules

    async def go():
        async with dbs.sessionmaker()() as db:
            return await fire_due_schedules(db)
    return _run(go())


@celery.task(name="isocline.worker.tasks.detect_drift")
def detect_drift() -> int:
    from isocline.services.monitoring import detect_all_drift

    async def go():
        async with dbs.sessionmaker()() as db:
            return await detect_all_drift(db)
    return _run(go())


@celery.task(name="isocline.worker.tasks.ingest_document")
def ingest_document(document_id: str) -> None:
    from isocline.services.knowledge import ingest_document as ingest

    async def go():
        async with dbs.sessionmaker()() as db:
            doc = await db.get(Document, uuid.UUID(document_id))
            if doc:
                await ingest(db, doc)
    _run(go())


@celery.task(name="isocline.worker.tasks.sweep_stale_runs")
def sweep_stale_runs() -> int:
    """Runs whose worker stopped heart-beating are re-queued (resume reuses completed nodes) up to 3 times,
    then failed explicitly. Nothing is left RUNNING forever."""
    s = get_settings()

    async def go():
        n = 0
        cutoff = utcnow() - timedelta(seconds=s.worker_stale_seconds)
        store = SqlRunStore(RedisBus(s.redis_url))
        async with dbs.sessionmaker()() as db:
            # A RUNNING run whose worker stopped heart-beating counts as a recovery attempt.
            stale = (await db.execute(select(Run).where(Run.status == "running", Run.heartbeat_at < cutoff))).scalars().all()
            # Runs that never started executing (queued, or resuming after a wait) are simply re-enqueued: this covers a
            # Redis restart losing the queue. Claiming is atomic, so a duplicate enqueue is harmless and not an "attempt".
            from isocline.services.recovery import requeue_pending
            n += len(await requeue_pending(db, s.worker_stale_seconds))
            for run in stale:
                n += 1
                if run.recovery_attempts >= 3:
                    run.status = "failed"
                    run.finished_at = utcnow()
                    run.error = {"code": "worker_lost", "message": "The worker executing this run stopped responding and recovery attempts were exhausted"}
                    await db.commit()
                    await store.emit(str(run.id), "RUN_FAILED", {"status": "failed", "error": run.error})
                else:
                    run.recovery_attempts += 1
                    await db.commit()
                    log.warning("run_recovery", run_id=str(run.id), attempt=run.recovery_attempts)
                    execute_run.delay(str(run.id))
        return n
    return _run(go())


@celery.task(name="isocline.worker.tasks.run_evaluation")
def run_evaluation(eval_run_id: str) -> dict:
    from isocline.services.evaluation import execute_evaluation
    return _run(execute_evaluation(eval_run_id))

