"""Alembic environment. Uses ISOCLINE_DATABASE_URL (async driver) and the ORM metadata."""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from isocline.core.config import get_settings
from isocline.db.models import Base

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _do(conn):
    context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_do)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
