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
    _engine = create_async_engine(url, **kwargs)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)


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
