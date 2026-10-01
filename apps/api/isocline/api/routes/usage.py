from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, membership, parse_uuid
from isocline.api.routes.runs import run_out
from isocline.db.models import NodeRun, Project, Run, UsageRecord, User, Workflow, utcnow
from isocline.db.session import get_db

router = APIRouter(tags=["usage"])


@router.get("/workspaces/{workspace_id}/dashboard")
async def dashboard(workspace_id: str, days: int = 30, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    wid = parse_uuid(workspace_id)
    since = utcnow() - timedelta(days=days)
    base = select(Run).where(Run.workspace_id == wid, Run.created_at >= since)
    agg = (await db.execute(select(func.count(Run.id), func.sum(Run.input_tokens + Run.output_tokens), func.sum(Run.cost_usd))
                            .where(Run.workspace_id == wid, Run.created_at >= since))).one()
    by_status = dict((await db.execute(select(Run.status, func.count(Run.id)).where(Run.workspace_id == wid, Run.created_at >= since)
                                       .group_by(Run.status))).all())
    finished = (await db.execute(base.where(Run.finished_at.is_not(None), Run.started_at.is_not(None)).limit(1000))).scalars().all()
    durations = [(r.finished_at - r.started_at).total_seconds() for r in finished]
    done = by_status.get("completed", 0) + by_status.get("failed", 0)
    recent_runs = (await db.execute(select(Run, Workflow.name).join(Workflow, Workflow.id == Run.workflow_id)
                                    .where(Run.workspace_id == wid).order_by(Run.created_at.desc()).limit(8))).all()
    recent_wf = (await db.execute(select(Workflow, Project.name).join(Project, Project.id == Workflow.project_id)
                                  .where(Project.workspace_id == wid, Workflow.status != "archived").order_by(Workflow.updated_at.desc()).limit(6))).all()
    failed_wf = (await db.execute(select(Workflow.id, Workflow.name, func.count(Run.id)).join(Run, Run.workflow_id == Workflow.id)
                                  .where(Run.workspace_id == wid, Run.status == "failed", Run.created_at >= since)
                                  .group_by(Workflow.id, Workflow.name).order_by(func.count(Run.id).desc()).limit(5))).all()
    models = (await db.execute(select(UsageRecord.provider, UsageRecord.model, func.count(UsageRecord.id),
                                      func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), func.sum(UsageRecord.cost_usd))
                               .where(UsageRecord.workspace_id == wid, UsageRecord.created_at >= since)
                               .group_by(UsageRecord.provider, UsageRecord.model).order_by(func.count(UsageRecord.id).desc()).limit(8))).all()
    agents = (await db.execute(select(NodeRun.node_key, Workflow.name, func.count(NodeRun.id), func.sum(NodeRun.input_tokens + NodeRun.output_tokens))
                               .join(Run, Run.id == NodeRun.run_id).join(Workflow, Workflow.id == Run.workflow_id)
                               .where(Run.workspace_id == wid, NodeRun.node_type == "agent", Run.created_at >= since)
                               .group_by(NodeRun.node_key, Workflow.name).order_by(func.count(NodeRun.id).desc()).limit(6))).all()
    return {
        "period_days": days,
        "total_runs": agg[0] or 0, "tokens": int(agg[1] or 0), "estimated_spend_usd": round(float(agg[2] or 0), 4),
        "cost_is_estimate": True, "runs_by_status": by_status,
        "success_rate": round(by_status.get("completed", 0) / done, 4) if done else None,
        "avg_duration_seconds": round(sum(durations) / len(durations), 2) if durations else None,
        "recent_runs": [run_out(r, wf_name=n) for r, n in recent_runs],
        "recent_workflows": [{"id": str(w.id), "name": w.name, "project_id": str(w.project_id), "project_name": pn,
                              "updated_at": w.updated_at.isoformat(), "status": w.status, "node_count": len((w.graph or {}).get("nodes", []))}
                             for w, pn in recent_wf],
        "failed_workflows": [{"id": str(i), "name": n, "failures": c} for i, n, c in failed_wf],
        "model_usage": [{"provider": p, "model": m, "calls": c, "tokens": int(t or 0), "cost_usd": round(float(s or 0), 4)} for p, m, c, t, s in models],
        "top_agents": [{"key": k, "workflow": w, "runs": c, "tokens": int(t or 0)} for k, w, c, t in agents],
    }


@router.get("/workspaces/{workspace_id}/usage")
async def usage(workspace_id: str, days: int = 30, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    wid = parse_uuid(workspace_id)
    since = utcnow() - timedelta(days=min(days, 365))
    day = cast(UsageRecord.created_at, Date)
    daily = (await db.execute(select(day, func.sum(UsageRecord.input_tokens), func.sum(UsageRecord.output_tokens), func.sum(UsageRecord.cost_usd),
                                     func.count(UsageRecord.id))
                              .where(UsageRecord.workspace_id == wid, UsageRecord.created_at >= since).group_by(day).order_by(day))).all()
    by_project = (await db.execute(select(Project.name, func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), func.sum(UsageRecord.cost_usd))
                                   .join(Project, Project.id == UsageRecord.project_id)
                                   .where(UsageRecord.workspace_id == wid, UsageRecord.created_at >= since).group_by(Project.name))).all()
    by_purpose = (await db.execute(select(UsageRecord.purpose, func.count(UsageRecord.id), func.sum(UsageRecord.cost_usd))
                                   .where(UsageRecord.workspace_id == wid, UsageRecord.created_at >= since).group_by(UsageRecord.purpose))).all()
    by_model = (await db.execute(select(UsageRecord.provider, UsageRecord.model, func.count(UsageRecord.id), func.sum(UsageRecord.input_tokens),
                                        func.sum(UsageRecord.output_tokens), func.sum(UsageRecord.cached_tokens), func.sum(UsageRecord.cost_usd),
                                        func.count(UsageRecord.cost_usd))
                                 .where(UsageRecord.workspace_id == wid, UsageRecord.created_at >= since)
                                 .group_by(UsageRecord.provider, UsageRecord.model))).all()
    return {
        "period_days": days, "cost_is_estimate": True,
        "note": "Costs are estimates from the server-side pricing table; providers' invoices are authoritative.",
        "daily": [{"date": str(d), "input_tokens": int(i or 0), "output_tokens": int(o or 0), "cost_usd": round(float(c or 0), 4), "calls": n}
                  for d, i, o, c, n in daily],
        "by_project": [{"project": p, "tokens": int(t or 0), "cost_usd": round(float(c or 0), 4)} for p, t, c in by_project],
        "by_purpose": [{"purpose": p, "calls": n, "cost_usd": round(float(c or 0), 4)} for p, n, c in by_purpose],
        "by_model": [{"provider": p, "model": m, "calls": n, "input_tokens": int(i or 0), "output_tokens": int(o or 0),
                      "cached_tokens": int(ca or 0), "cost_usd": round(float(c or 0), 4), "unpriced_calls": n - (priced or 0)}
                     for p, m, n, i, o, ca, c, priced in by_model],
    }


@router.get("/workspaces/{workspace_id}/audit")
async def audit_log(workspace_id: str, limit: int = 100, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.db.models import AuditEvent
    await membership(db, user, workspace_id, "admin")
    rows = (await db.execute(select(AuditEvent, User.email).outerjoin(User, User.id == AuditEvent.user_id)
                             .where(AuditEvent.workspace_id == parse_uuid(workspace_id)).order_by(AuditEvent.created_at.desc())
                             .limit(min(limit, 500)))).all()
    return [{"id": str(a.id), "action": a.action, "user": e, "target_type": a.target_type, "target_id": a.target_id,
             "data": a.data, "created_at": a.created_at.isoformat()} for a, e in rows]
