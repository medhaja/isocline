from __future__ import annotations

import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, load_workflow, membership, parse_uuid
from isocline.core.errors import AppError, bad_request, not_found
from isocline.core.security import encrypt_secret
from isocline.db.models import User, utcnow
from isocline.db.models_v2 import Trigger, TriggerDelivery
from isocline.db.session import get_db
from isocline.services.audit import audit

router = APIRouter(tags=["triggers"])
public = APIRouter(tags=["public triggers"])


class TriggerIn(BaseModel):
    workflow_id: str
    kind: Literal["webhook", "schedule", "event", "file"]
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


def trig_out(t: Trigger) -> dict:
    d = dump(t, "id", "project_id", "workflow_id", "kind", "name", "enabled", "config", "next_run_at", "last_run_at", "created_at")
    if t.kind == "webhook":
        d["path"] = f"/hooks/{t.public_id}"
    return d


def _check_config(kind: str, cfg: dict) -> dict:
    from isocline.services.triggers import parse_cron
    cfg = dict(cfg)
    if kind == "schedule":
        try:
            parse_cron(cfg.get("cron") or "")
            from zoneinfo import ZoneInfo
            ZoneInfo(cfg.get("timezone") or "UTC")
        except Exception as e:
            raise bad_request(f"Invalid schedule: {e}") from e
    if kind == "event" and not cfg.get("event_name"):
        raise bad_request("Event triggers need an event_name")
    if kind == "webhook" and cfg.get("auth", "hmac") not in ("hmac", "token"):
        raise bad_request("Webhook auth must be 'hmac' or 'token'")
    return cfg


@router.get("/projects/{project_id}/triggers")
async def list_triggers(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    rows = (await db.execute(select(Trigger).where(Trigger.project_id == p.id).order_by(Trigger.created_at.desc()))).scalars().all()
    return [trig_out(t) for t in rows]


@router.post("/projects/{project_id}/triggers", status_code=201)
async def create_trigger(project_id: str, body: TriggerIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.triggers import next_fire
    p = await load_project(db, user, project_id, "editor")
    wf, wp = await load_workflow(db, user, body.workflow_id, "editor")
    if wp.id != p.id:
        raise bad_request("Workflow belongs to another project")
    if wf.latest_version == 0:
        raise bad_request("Publish the workflow first: triggers always run a published version")
    cfg = _check_config(body.kind, body.config)
    secret = None
    t = Trigger(project_id=p.id, workflow_id=wf.id, kind=body.kind, name=body.name, enabled=body.enabled, config=cfg, created_by=user.id)
    if body.kind == "webhook":
        secret = secrets.token_urlsafe(32)
        t.public_id, t.secret_encrypted = secrets.token_urlsafe(18), encrypt_secret(secret)
    if body.kind == "schedule":
        t.next_run_at = next_fire(cfg["cron"], utcnow(), cfg.get("timezone", "UTC"))
    db.add(t)
    await db.flush()
    await audit(db, "trigger_created", user_id=user.id, workspace_id=p.workspace_id, target_id=t.id, data={"kind": body.kind})
    await db.commit()
    out = trig_out(t)
    if secret:
        out["secret"] = secret
        out["warning"] = "Copy the signing secret now. It will not be shown again."
    return out


@router.put("/triggers/{trigger_id}")
async def update_trigger(trigger_id: str, body: TriggerIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.triggers import next_fire
    t = await db.get(Trigger, parse_uuid(trigger_id, "Trigger"))
    if t is None:
        raise not_found("Trigger")
    await load_project(db, user, t.project_id, "editor")
    t.name, t.enabled, t.config = body.name, body.enabled, _check_config(t.kind, body.config)
    if t.kind == "schedule":
        t.next_run_at = next_fire(t.config["cron"], utcnow(), t.config.get("timezone", "UTC"))
    await db.commit()
    return trig_out(t)


@router.delete("/triggers/{trigger_id}", status_code=204)
async def delete_trigger(trigger_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(Trigger, parse_uuid(trigger_id, "Trigger"))
    if t is None:
        raise not_found("Trigger")
    p = await load_project(db, user, t.project_id, "editor")
    await audit(db, "trigger_deleted", user_id=user.id, workspace_id=p.workspace_id, target_id=t.id)
    from sqlalchemy import delete as sdel
    await db.execute(sdel(TriggerDelivery).where(TriggerDelivery.trigger_id == t.id))
    await db.delete(t)
    await db.commit()


@router.get("/schedules/preview")
async def schedule_preview(cron: str, timezone: str = "UTC", user: User = Depends(current_user)):
    from isocline.services.triggers import next_fire
    try:
        out, t = [], utcnow()
        for _ in range(5):
            t = next_fire(cron, t, timezone)
            out.append(t.isoformat())
        return {"next": out}
    except Exception as e:
        raise bad_request(str(e)) from e


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    correlation_key: str | None = Field(default=None, max_length=300)
    payload: Any = None


@router.post("/workspaces/{workspace_id}/events", status_code=202)
async def publish(workspace_id: str, body: EventIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Delivers an external event: resumes matching durable waits and starts event-triggered workflows."""
    from isocline.services.triggers import fire_event_triggers
    from isocline.services.waits import publish_event
    await membership(db, user, workspace_id, "workflows:execute")
    wid = parse_uuid(workspace_id)
    res = await publish_event(db, wid, body.name, body.correlation_key, body.payload)
    runs = await fire_event_triggers(db, wid, body.name, body.correlation_key, body.payload)
    return {**res, "runs_started": runs}


# ------------------------------------------------------------------ public endpoints (no session)
@public.post("/hooks/{public_id}", status_code=202)
async def webhook(public_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from isocline.services.triggers import deliver_webhook
    t = (await db.execute(select(Trigger).where(Trigger.public_id == public_id, Trigger.kind == "webhook"))).scalar_one_or_none()
    if t is None:
        raise not_found("Webhook")
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise AppError(413, "too_large", "Payload exceeds 1 MB")
    return await deliver_webhook(db, t, {k.lower(): v for k, v in request.headers.items()}, body)


@public.post("/callbacks/{run_id}/{node_id}/{token}", status_code=202)
async def callback(run_id: str, node_id: str, token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Resumes a 'Wait for webhook' node. The URL itself is the capability (HMAC over run and node)."""
    import json
    from isocline.services.waits import resolve_callback, verify_callback
    if not verify_callback(run_id, node_id, token):
        raise AppError(401, "invalid_callback", "Invalid callback URL")
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise AppError(413, "too_large", "Payload exceeds 1 MB")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {"body": raw.decode("utf-8", "replace")}
    return {"status": await resolve_callback(db, run_id, node_id, payload)}
