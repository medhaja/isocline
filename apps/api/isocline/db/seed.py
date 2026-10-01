"""Idempotent seeding of reference data: providers, model catalog/pricing and agent templates.
Never overwrites rows an administrator has edited."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import AgentTemplate, ModelPricing, Provider
from isocline.engine.agent_templates import AGENT_TEMPLATES
from isocline.providers.registry import provider_classes

CATALOG = Path(__file__).resolve().parent.parent / "data" / "model_catalog.json"


async def seed(db: AsyncSession) -> None:
    for pid, cls in provider_classes().items():
        if await db.get(Provider, pid) is None:
            db.add(Provider(id=pid, name=cls.name, kind=pid, default_base_url=cls.default_base_url, requires_key=cls.requires_key))
    existing = {(p, m) for p, m in (await db.execute(select(ModelPricing.provider, ModelPricing.model))).all()}
    for row in json.loads(CATALOG.read_text())["models"]:
        if (row["provider"], row["model"]) not in existing:
            db.add(ModelPricing(**row))
    for tid, t in AGENT_TEMPLATES.items():
        if await db.get(AgentTemplate, tid) is None:
            db.add(AgentTemplate(id=tid, name=t["name"], description=t["description"], icon=t.get("icon", ""),
                                 config={"role": t["role"], "instructions": t["instructions"], "tools": t["tools"]}))
    await db.commit()


async def bootstrap_admin(db: AsyncSession) -> None:
    """Headless setup: ISOCLINE_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD create the first (admin) account when the
    installation has none. Never touches an existing account, and never logs the password."""
    from sqlalchemy import func

    from isocline.core.config import get_settings
    from isocline.core.logging import log
    from isocline.db.models import User
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    if (await db.execute(select(func.count(User.id)))).scalar():
        return
    if len(s.bootstrap_admin_password) < 10:
        log.error("bootstrap_admin_skipped", reason="ISOCLINE_BOOTSTRAP_ADMIN_PASSWORD must be at least 10 characters")
        return
    from isocline.api.routes.auth import create_account
    await create_account(db, s.bootstrap_admin_email.lower(), s.bootstrap_admin_password, is_admin=True)
    await db.commit()
    log.info("bootstrap_admin_created", email=s.bootstrap_admin_email.lower())
