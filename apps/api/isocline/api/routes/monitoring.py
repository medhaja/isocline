from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, membership, parse_uuid
from isocline.core.errors import not_found
from isocline.db.models import Run, User, Workflow, utcnow
from isocline.db.models_v2 import DriftEvent
from isocline.db.session import get_db
from isocline.services import monitoring as mon

router = APIRouter(tags=["monitoring"])


@router.get("/projects/{project_id}/monitoring")
async def project_monitoring(project_id: str, hours: int = 168, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """One card per workflow that ran in the window, with metrics, plus open drift alerts."""
    p = await load_project(db, user, project_id)
    since = utcnow() - timedelta(hours=min(hours, 24 * 90))
    targets = []
    ran = set((await db.execute(select(Run.workflow_id).where(Run.project_id == p.id, Run.created_at >= since).distinct())).scalars().all())
    for wf in (await db.execute(select(Workflow).where(Workflow.project_id == p.id).order_by(Workflow.name))).scalars():
        if wf.id not in ran:
            continue
        m = await mon.run_metrics(db, workflow_id=wf.id, since=since, bucket_hours=6 if hours > 48 else 1)
        targets.append({"kind": "workflow", "id": str(wf.id), "name": wf.name, "workflow_id": str(wf.id), "workflow_name": wf.name,
                        "version": wf.latest_version, "metrics": m})
    wf_ids = (await db.execute(select(Workflow.id).where(Workflow.project_id == p.id))).scalars().all()
    alerts = (await db.execute(select(DriftEvent).where(DriftEvent.workflow_id.in_(wf_ids)).order_by(DriftEvent.created_at.desc()).limit(100))).scalars().all() if wf_ids else []
    return {"targets": targets, "alerts": [alert_out(a) for a in alerts]}


def alert_out(a: DriftEvent) -> dict:
    return dump(a, "id", "workflow_id", "metric", "severity", "baseline", "current", "message", "primary_node_key", "created_at", "acknowledged_at")


@router.post("/projects/{project_id}/monitoring/detect")
async def detect_now(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "editor")
    n = 0
    for wid in (await db.execute(select(Workflow.id).where(Workflow.project_id == p.id))).scalars().all():
        n += len(await mon.detect_drift(db, wid))
    return {"new_alerts": n}


@router.post("/alerts/{alert_id}/acknowledge")
async def ack(alert_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(DriftEvent, parse_uuid(alert_id, "Alert"))
    if a is None:
        raise not_found("Alert")
    await membership(db, user, a.workspace_id, "editor")
    a.acknowledged_at = utcnow()
    await db.commit()
    return alert_out(a)


@router.get("/workspaces/{workspace_id}/alerts")
async def workspace_alerts(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(DriftEvent, Workflow.name).join(Workflow, Workflow.id == DriftEvent.workflow_id)
                             .where(DriftEvent.workspace_id == parse_uuid(workspace_id), DriftEvent.acknowledged_at.is_(None))
                             .order_by(DriftEvent.created_at.desc()).limit(50))).all()
    return [{**alert_out(a), "workflow_name": n} for a, n in rows]
