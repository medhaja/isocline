"""Run dispatch. Production uses Celery; tests swap in an in-process dispatcher."""
from __future__ import annotations

from typing import Callable

_dispatcher: Callable[[str], None] | None = None
_ingest_dispatcher: Callable[[str], None] | None = None


def set_dispatcher(fn: Callable[[str], None] | None) -> None:
    global _dispatcher
    _dispatcher = fn


_inline_tasks: set = set()


def _inline(coro_factory) -> bool:
    """Dev-only in-process execution (ISOCLINE_INLINE_WORKER=true)."""
    from isocline.core.config import get_settings
    if not get_settings().inline_worker:
        return False
    import asyncio
    t = asyncio.get_running_loop().create_task(coro_factory())
    _inline_tasks.add(t)
    t.add_done_callback(_inline_tasks.discard)
    return True


async def _run_inline(run_id: str):
    from isocline.engine.events import NullBus
    from isocline.engine.executor import Executor
    from isocline.engine.store import SqlRunStore
    await Executor(SqlRunStore(NullBus()), run_id, "inline-dev-worker").execute()


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
    if _inline(lambda: _run_inline(str(run_id))):
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
    if _inline(lambda: _ingest_inline(str(document_id))):
        return
    from isocline.worker.tasks import ingest_document
    ingest_document.delay(str(document_id))

