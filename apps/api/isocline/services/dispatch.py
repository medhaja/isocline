"""Run dispatch. The server stack uses Celery; desktop mode and the dev inline worker run work in-process;
tests swap in their own dispatcher."""
from __future__ import annotations

from typing import Callable

_dispatcher: Callable[[str], None] | None = None
_ingest_dispatcher: Callable[[str], None] | None = None


def set_dispatcher(fn: Callable[[str], None] | None) -> None:
    global _dispatcher
    _dispatcher = fn


_inline_tasks: set = set()
_inflight: set[str] = set()  # keys of work already queued or running in this process
_slots = None  # asyncio.Semaphore, created lazily on the running loop


def _semaphore():
    global _slots
    if _slots is None:
        import asyncio
        from isocline.core.config import get_settings
        _slots = asyncio.Semaphore(max(1, get_settings().desktop_concurrency))
    return _slots


def _inline(coro_factory, key: str | None = None) -> bool:
    """In-process execution: desktop mode, or the dev inline worker (ISOCLINE_INLINE_WORKER=true).

    Work waits for one of ``desktop_concurrency`` slots, and a key that is already queued or running in this process is
    not queued twice (the stale-run sweeper re-enqueues waiting runs; claiming is atomic anyway, this just avoids piles
    of redundant tasks)."""
    from isocline.core.config import get_settings
    if not get_settings().in_process_worker:
        return False
    if key is not None and key in _inflight:
        return True
    import asyncio

    async def guarded():
        try:
            async with _semaphore():
                await coro_factory()
        except Exception as e:  # executor failures are recorded on the run; this only catches crashes around it
            from isocline.core.logging import log
            log.exception("in_process_task_failed", key=key, error=str(e))
        finally:
            if key is not None:
                _inflight.discard(key)

    if key is not None:
        _inflight.add(key)
    t = asyncio.get_running_loop().create_task(guarded())
    _inline_tasks.add(t)
    t.add_done_callback(_inline_tasks.discard)
    return True


def inflight() -> set[str]:
    return set(_inflight)


async def drain(timeout: float = 10.0) -> None:
    """Gives in-process work a chance to finish on shutdown; unfinished runs are recovered on the next start."""
    import asyncio
    if _inline_tasks:
        await asyncio.wait(set(_inline_tasks), timeout=timeout)


async def _run_inline(run_id: str):
    from isocline.engine.events import NullBus
    from isocline.engine.executor import Executor
    from isocline.engine.store import SqlRunStore
    from isocline.core.config import get_settings
    worker = "desktop" if get_settings().desktop else "inline-dev-worker"
    await Executor(SqlRunStore(NullBus()), run_id, worker).execute()


async def _ingest_inline(document_id: str):
    import uuid
    from isocline.db import session as dbs
    from isocline.db.models import Document
    from isocline.services.knowledge import ingest_document
    async with dbs.sessionmaker()() as db:
        doc = await db.get(Document, uuid.UUID(document_id))
        if doc:
            await ingest_document(db, doc)


def enqueue_run(run_id: str) -> None:
    if _dispatcher is not None:
        _dispatcher(str(run_id))
        return
    if _inline(lambda: _run_inline(str(run_id)), key=f"run:{run_id}"):
        return
    from isocline.worker.tasks import execute_run
    execute_run.delay(str(run_id))


def set_ingest_dispatcher(fn: Callable[[str], None] | None) -> None:
    global _ingest_dispatcher
    _ingest_dispatcher = fn


def enqueue_ingest(document_id: str) -> None:
    if _ingest_dispatcher is not None:
        _ingest_dispatcher(str(document_id))
        return
    if _inline(lambda: _ingest_inline(str(document_id)), key=f"ingest:{document_id}"):
        return
    from isocline.worker.tasks import ingest_document
    ingest_document.delay(str(document_id))

