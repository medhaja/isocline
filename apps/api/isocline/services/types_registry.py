"""Workspace custom types (JSON Schemas usable as JSON<Name> in contracts)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models_v2 import CustomType


async def custom_types_for(db: AsyncSession, workspace_id) -> dict[str, dict]:
    rows = (await db.execute(select(CustomType.name, CustomType.json_schema).where(CustomType.workspace_id == workspace_id))).all()
    return {n: s for n, s in rows}
