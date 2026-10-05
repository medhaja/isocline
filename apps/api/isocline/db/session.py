"""Async engine/session management. Workers use NullPool because each Celery task runs its own event loop."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from isocline.core.config import get_settings

_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None


def configure(url: str | None = None, *, worker: bool = False) -> None:
    global _engine, _maker
    url = url or get_settings().database_url
    kwargs = {"poolclass": NullPool} if worker or url.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    _engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        _sqlite_pragmas(_engine)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)


def _sqlite_pragmas(eng: AsyncEngine) -> None:
    """WAL lets the UI read while a run writes; busy_timeout makes concurrent writers wait instead of failing."""
    from sqlalchemy import event

    @event.listens_for(eng.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        if ":memory:" not in str(eng.url):
            cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def engine() -> AsyncEngine:
    if _engine is None:
        configure()
    return _engine  # type: ignore[return-value]


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _maker is None:
        configure()
    return _maker  # type: ignore[return-value]


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        yield s
