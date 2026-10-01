"""Saga-style compensation. Registered compensations run in reverse order, only when the workflow enables automatic
compensation or a user triggers them. Each compensating action passes the policy engine; when a policy requires
approval, automatic compensation skips it (a user triggering it manually is the approval)."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from isocline.core.logging import log, redact
from isocline.db import session as dbs
from isocline.db.models import Run, utcnow
from isocline.db.models_v2 import CompensationAction
from isocline.engine.policy import evaluate_tool, tool_action
from isocline.tools.base import ToolContext
from isocline.tools.builtin import TOOLS


async def run_compensations(run_id: str, actor: str = "policy", only_ids: list[str] | None = None) -> dict:
    results = {"succeeded": 0, "failed": 0, "skipped": 0}
    async with dbs.sessionmaker()() as db:
        run = await db.get(Run, uuid.UUID(str(run_id)))
        if run is None:
            return results
        policy = (run.settings or {}).get("_policy") or []
        q = select(CompensationAction).where(CompensationAction.run_id == run.id, CompensationAction.status == "available")
        actions = (await db.execute(q.order_by(CompensationAction.sequence.desc()))).scalars().all()
        for a in actions:
            if only_ids and str(a.id) not in only_ids:
                continue
            comp = a.compensation or {}
            args = comp.get("arguments") or {}
            tool = comp.get("tool") or "http_request"
            action = tool_action(tool, args)
            d = evaluate_tool(policy, tool, action, {"node_key": a.node_key, "args": args})
            a.attempted_at, a.attempted_by = utcnow(), actor
            if d.effect == "deny" or (d.effect == "require_approval" and actor == "policy"):
                a.status = "skipped"
                a.result = {"reason": f"policy: {d.reason}" + (" — run it manually from the run page" if d.effect == "require_approval" else "")}
                results["skipped"] += 1
                continue

            secrets: list[str] = []

            async def get_secret(name: str):
                from isocline.engine.store import SqlRunStore
                v = await SqlRunStore().secret_by_name(run.workspace_id, name)
                if v:
                    secrets.append(v)
                return v
            tctx = ToolContext(workspace_id=str(run.workspace_id), project_id=str(run.project_id), run_id=str(run.id),
                               get_secret=get_secret, knowledge_base_ids=[], open_session=dbs.sessionmaker())
            try:
                out = await TOOLS[tool].execute(args, tctx)
                a.status, a.result = "succeeded", redact(out, secrets)
                results["succeeded"] += 1
            except Exception as e:
                a.status, a.result = "failed", {"error": str(e)[:1000]}
                results["failed"] += 1
                log.warning("compensation_action_failed", run_id=str(run_id), node=a.node_key, error=str(e))
        from isocline.services.audit import audit
        await audit(db, "compensation_executed", workspace_id=run.workspace_id, target_type="run", target_id=run.id,
                    data={**results, "actor": actor})
        await db.commit()
    return results
