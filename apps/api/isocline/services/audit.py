"""Audit events and product analytics. Analytics events never contain prompt/output content."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.logging import log, redact
from isocline.db.models import AuditEvent

ANALYTICS_EVENTS = {"workflow_created", "workflow_run", "workflow_completed", "workflow_failed", "agent_created",
                    "template_used", "evaluation_run"}


async def audit(db: AsyncSession, action: str, *, user_id=None, workspace_id=None, target_type: str | None = None,
                target_id=None, data: dict | None = None, ip: str | None = None, commit: bool = False) -> None:
    db.add(AuditEvent(workspace_id=workspace_id, user_id=user_id, action=action, target_type=target_type,
                      target_id=str(target_id) if target_id else None, data=redact(data or {}), ip=ip))
    if action in ANALYTICS_EVENTS:
        log.info("product_event", product_event=action, workspace_id=str(workspace_id) if workspace_id else None,
                 target_id=str(target_id) if target_id else None)
    if commit:
        await db.commit()
