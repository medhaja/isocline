from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, load_run, load_workflow, parse_uuid
from isocline.core.config import get_settings
from isocline.core.errors import not_found
from isocline.db import session as dbs
from isocline.db.models import Approval, NodeRun, Run, RunEvent, ToolRun, User, Workflow
from isocline.db.session import get_db
from isocline.services.runs import cancel_run, decide_approval, replay_run

router = APIRouter(tags=["runs"])
TERMINAL = {"completed", "failed", "cancelled"}

RUN_FIELDS = ("id", "workflow_id", "workflow_version_id", "project_id", "status", "trigger", "input", "output", "error",
              "parent_run_id", "replay_from_node_id", "created_at", "started_at", "finished_at", "llm_calls",
              "tool_calls", "input_tokens", "output_tokens", "cost_usd", "cost_is_estimate", "recovery_attempts")


def run_out(r: Run, full: bool = False, wf_name: str | None = None) -> dict:
    d = dump(r, *RUN_FIELDS)
    if r.started_at and r.finished_at:
        d["duration_ms"] = int((r.finished_at - r.started_at).total_seconds() * 1000)
    d["limits"] = {k: v for k, v in (r.settings or {}).items() if k.startswith("max_")}
    if wf_name is not None:
        d["workflow_name"] = wf_name
    if full:
        d["graph_snapshot"] = r.graph_snapshot
    return d


def node_out(n: NodeRun) -> dict:
    return dump(n, "id", "node_id", "node_key", "node_type", "scope", "status", "input", "config", "output", "handle", "error",
                "attempts", "provider", "model", "fallback_used", "llm_calls", "input_tokens", "output_tokens", "cached_tokens",
                "cost_usd", "reasoning_summary", "started_at", "finished_at", "latency_ms",
                agent_id=str(n.agent_id) if n.agent_id else None)


def tool_out(t: ToolRun) -> dict:
    return dump(t, "id", "node_run_id", "tool", "input", "output", "success", "error", "started_at", "finished_at", "duration_ms")


class ReplayIn(BaseModel):
    node_id: str
    use_current_draft: bool = False


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    edited_content: Any = None
    comment: str | None = Field(default=None, max_length=10000)


@router.get("/projects/{project_id}/runs")
async def project_runs(project_id: str, workflow_id: str | None = None, status: str | None = None, limit: int = 50,
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    q = select(Run, Workflow.name).join(Workflow, Workflow.id == Run.workflow_id).where(Run.project_id == p.id)
    if workflow_id:
        q = q.where(Run.workflow_id == parse_uuid(workflow_id))
    if status:
        q = q.where(Run.status == status)
    rows = (await db.execute(q.order_by(Run.created_at.desc()).limit(min(limit, 200)))).all()
    return [run_out(r, wf_name=n) for r, n in rows]


@router.get("/workflows/{workflow_id}/runs")
async def workflow_runs(workflow_id: str, limit: int = 30, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    wf, _ = await load_workflow(db, user, workflow_id)
    rows = (await db.execute(select(Run).where(Run.workflow_id == wf.id).order_by(Run.created_at.desc()).limit(min(limit, 200)))).scalars().all()
    return [run_out(r, wf_name=wf.name) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await load_run(db, user, run_id)
    wf = await db.get(Workflow, r.workflow_id)
    approvals = (await db.execute(select(Approval).where(Approval.run_id == r.id).order_by(Approval.created_at))).scalars().all()
    children = (await db.execute(select(Run.id, Run.status, Run.created_at).where(Run.parent_run_id == r.id))).all()
    return {**run_out(r, full=True, wf_name=wf.name if wf else None),
            "approvals": [approval_out(a) for a in approvals],
            "replays": [{"id": str(i), "status": s, "created_at": c.isoformat()} for i, s, c in children]}


def approval_out(a: Approval) -> dict:
    return dump(a, "id", "run_id", "node_id", "scope", "status", "title", "instructions", "content", "allow_edit", "edited_content",
                "comment", "decided_at", "created_at")


@router.get("/runs/{run_id}/nodes")
async def run_nodes(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await load_run(db, user, run_id)
    nodes = (await db.execute(select(NodeRun).where(NodeRun.run_id == r.id).order_by(NodeRun.started_at))).scalars().all()
    tools = (await db.execute(select(ToolRun).where(ToolRun.run_id == r.id).order_by(ToolRun.started_at))).scalars().all()
    by_node: dict[str, list] = {}
    for t in tools:
        by_node.setdefault(str(t.node_run_id), []).append(tool_out(t))
    return [{**node_out(n), "tool_runs": by_node.get(str(n.id), [])} for n in nodes]


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await load_run(db, user, run_id, "workflows:execute")
    r = await cancel_run(db, r)
    return run_out(r)


@router.post("/runs/{run_id}/replay", status_code=202)
async def replay(run_id: str, body: ReplayIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    parent = await load_run(db, user, run_id, "workflows:execute")
    wf, p = await load_workflow(db, user, parent.workflow_id, "workflows:execute")
    child = await replay_run(db, parent, body.node_id, user_id=user.id, use_current_draft=body.use_current_draft, workflow=wf, project=p)
    return {"run_id": str(child.id), "status": child.status, "parent_run_id": str(parent.id)}


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, after: int = 0, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Server-Sent Events. Replays persisted events (so a refreshed page reconstructs state), then streams live
    events. Delivery uses Redis pub/sub as a wake-up signal with the database as the source of truth."""
    r = await load_run(db, user, run_id)
    rid = r.id
    last_event_id = request.headers.get("last-event-id")
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    async def fetch(since: int) -> tuple[list[RunEvent], str]:
        async with dbs.sessionmaker()() as s:
            evs = (await s.execute(select(RunEvent).where(RunEvent.run_id == rid, RunEvent.seq > since).order_by(RunEvent.seq))).scalars().all()
            status = (await s.execute(select(Run.status).where(Run.id == rid))).scalar()
            return list(evs), status

    def fmt(ev: RunEvent) -> str:
        payload = {"seq": ev.seq, "type": ev.type, "data": ev.data, "ts": ev.created_at.isoformat() if ev.created_at else None}
        return f"id: {ev.seq}\nevent: message\ndata: {json.dumps(payload, default=str)}\n\n"

    async def stream():
        last = start
        sub = None
        try:
            import redis.asyncio as redis
            from isocline.engine.events import channel
            client = redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5)
            sub = client.pubsub()
            await sub.subscribe(channel(str(rid)))
        except Exception:
            sub = None
        try:
            yield "retry: 2000\n\n"
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    break
                evs, status = await fetch(last)
                for ev in evs:
                    last = ev.seq
                    yield fmt(ev)
                if status in TERMINAL:
                    # Final state reached and all persisted events flushed.
                    yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                    break
                woke = False
                if sub is not None:
                    try:
                        msg = await sub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        woke = msg is not None
                    except Exception:
                        sub = None
                if sub is None and not woke:
                    await asyncio.sleep(0.5)
                idle = 0.0 if (evs or woke) else idle + 1
                if idle >= 15:
                    idle = 0.0
                    yield ": keepalive\n\n"
        finally:
            if sub is not None:
                try:
                    await sub.aclose()
                except Exception:
                    pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                                      "Content-Encoding": "identity", "Connection": "keep-alive"})


@router.get("/runs/{run_id}/events.json")
async def events_json(run_id: str, after: int = 0, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await load_run(db, user, run_id)
    evs = (await db.execute(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.seq > after).order_by(RunEvent.seq))).scalars().all()
    return [{"seq": e.seq, "type": e.type, "data": e.data, "ts": e.created_at.isoformat()} for e in evs]


@router.get("/runs/compare/{a}/{b}")
async def compare(a: str, b: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ra, rb = await load_run(db, user, a), await load_run(db, user, b)
    na = {(n.node_id, n.scope): n for n in (await db.execute(select(NodeRun).where(NodeRun.run_id == ra.id))).scalars().all()}
    nb = {(n.node_id, n.scope): n for n in (await db.execute(select(NodeRun).where(NodeRun.run_id == rb.id))).scalars().all()}
    ga = {n["id"]: n for n in ra.graph_snapshot.get("nodes", [])}
    gb = {n["id"]: n for n in rb.graph_snapshot.get("nodes", [])}
    rows = []
    for key in sorted(set(na) | set(nb) | {(k, "") for k in set(ga) | set(gb)}, key=lambda k: (k[1], k[0])):
        x, y = na.get(key), nb.get(key)
        cx, cy = (ga.get(key[0]) or {}).get("config"), (gb.get(key[0]) or {}).get("config")
        node = ga.get(key[0]) or gb.get(key[0]) or {}
        if node.get("type") in ("group", "note"):
            continue

        def side(n: NodeRun | None, cfg):
            if n is None:
                return None
            return {"status": n.status, "provider": n.provider, "model": n.model, "input_tokens": n.input_tokens,
                    "output_tokens": n.output_tokens, "cost_usd": n.cost_usd, "latency_ms": n.latency_ms, "output": n.output,
                    "error": n.error, "prompt": (cfg or {}).get("prompt"), "instructions": (cfg or {}).get("instructions"),
                    "params": (cfg or {}).get("params")}
        sa, sb = side(x, cx), side(y, cy)
        rows.append({"node_id": key[0], "scope": key[1], "key": node.get("key"), "name": node.get("name"), "type": node.get("type"),
                     "a": sa, "b": sb, "config_changed": cx != cy,
                     "output_changed": (sa or {}).get("output") != (sb or {}).get("output")})
    return {"a": run_out(ra), "b": run_out(rb), "input_changed": ra.input != rb.input, "nodes": rows}


@router.get("/runs/{run_id}/approvals")
async def run_approvals(run_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await load_run(db, user, run_id)
    rows = (await db.execute(select(Approval).where(Approval.run_id == r.id).order_by(Approval.created_at))).scalars().all()
    return [approval_out(a) for a in rows]


@router.get("/workspaces/{workspace_id}/approvals")
async def pending_approvals(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.api.deps import membership
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(Approval, Run.workflow_id, Workflow.name).join(Run, Run.id == Approval.run_id)
                             .join(Workflow, Workflow.id == Run.workflow_id)
                             .where(Run.workspace_id == parse_uuid(workspace_id), Approval.status == "pending")
                             .order_by(Approval.created_at.desc()))).all()
    return [{**approval_out(a), "workflow_id": str(w), "workflow_name": n} for a, w, n in rows]


@router.post("/approvals/{approval_id}/decide")
async def decide(approval_id: str, body: DecisionIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Approval, parse_uuid(approval_id, "Approval"))
    if a is None:
        raise not_found("Approval")
    r = await load_run(db, user, a.run_id, "approvals:decide")
    from isocline.services.audit import audit
    a = await decide_approval(db, r, a, decision=body.decision, user_id=user.id, edited_content=body.edited_content, comment=body.comment)
    await audit(db, "approval_decided", user_id=user.id, workspace_id=r.workspace_id, target_id=a.id, data={"decision": body.decision},
                commit=True)
    return approval_out(a)
