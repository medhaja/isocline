"""Durable run state. The executor never keeps authoritative state only in memory: every node
transition, tool call, usage record and event is persisted so a run can be reconstructed after a
browser refresh or resumed after a worker crash."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from isocline.core.logging import log, redact
from isocline.core.security import decrypt_secret
from isocline.db import session as dbs
from isocline.db.models import (
    Approval, ModelPricing, NodeRun, ProviderCredential, Run, RunEvent, ToolRun, UsageRecord, WorkflowMemory, utcnow,
)

from .events import EventBus, NullBus

TERMINAL_NODE = {"completed", "failed", "skipped", "cancelled"}


def _uuid(v) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


from isocline.engine.store_v2 import HarnessStoreMixin  # noqa: E402


class SqlRunStore(HarnessStoreMixin):
    def __init__(self, bus: EventBus | None = None):
        self.bus = bus or NullBus()
        self._seq: dict[str, int] = {}

    def session(self):
        return dbs.sessionmaker()()

    # ------------------------------------------------------------------ runs
    async def claim_run(self, run_id: str, worker_id: str, stale_seconds: int) -> dict | None:
        """Atomically claims a run for execution so two workers never execute it concurrently."""
        rid = _uuid(run_id)
        now = utcnow()
        stale = now - timedelta(seconds=stale_seconds)
        async with self.session() as s:
            res = await s.execute(
                update(Run).where(
                    Run.id == rid,
                    (Run.status.in_(["queued", "resuming"])) | ((Run.status == "running") & ((Run.heartbeat_at == None) | (Run.heartbeat_at < stale))),  # noqa: E711
                ).values(status="running", worker_id=worker_id, heartbeat_at=now,
                         started_at=func.coalesce(Run.started_at, now))
            )
            await s.commit()
            if res.rowcount != 1:
                return None
            run = await s.get(Run, rid)
            last = (await s.execute(select(func.max(RunEvent.seq)).where(RunEvent.run_id == rid))).scalar()
            self._seq[str(rid)] = last or 0
            return {c.name: getattr(run, c.name) for c in Run.__table__.columns}

    async def heartbeat(self, run_id: str, worker_id: str) -> bool:
        """Returns True if cancellation was requested."""
        async with self.session() as s:
            await s.execute(update(Run).where(Run.id == _uuid(run_id), Run.worker_id == worker_id).values(heartbeat_at=utcnow()))
            await s.commit()
            return bool((await s.execute(select(Run.cancel_requested).where(Run.id == _uuid(run_id)))).scalar())

    async def finish_run(self, run_id: str, status: str, output: Any = None, error: Any = None, totals: dict | None = None) -> None:
        async with self.session() as s:
            values: dict[str, Any] = {"status": status, "heartbeat_at": utcnow()}
            if status in ("completed", "failed", "cancelled"):
                values["finished_at"] = utcnow()
            if output is not None:
                values["output"] = output
            values["error"] = error
            if totals:
                values.update(totals)
            await s.execute(update(Run).where(Run.id == _uuid(run_id)).values(**values))
            await s.commit()

    async def update_totals(self, run_id: str, totals: dict) -> None:
        async with self.session() as s:
            await s.execute(update(Run).where(Run.id == _uuid(run_id)).values(**totals))
            await s.commit()

    # ------------------------------------------------------------------ events
    async def emit(self, run_id: str, type_: str, data: dict | None = None) -> None:
        rid = str(run_id)
        data = redact(data or {})
        for _ in range(5):
            seq = self._seq.get(rid, 0) + 1
            self._seq[rid] = seq
            ev = {"run_id": rid, "seq": seq, "type": type_, "data": data, "ts": utcnow().isoformat()}
            try:
                async with self.session() as s:
                    s.add(RunEvent(run_id=_uuid(rid), seq=seq, type=type_, data=data))
                    await s.commit()
                break
            except IntegrityError:
                async with self.session() as s:
                    self._seq[rid] = (await s.execute(select(func.max(RunEvent.seq)).where(RunEvent.run_id == _uuid(rid)))).scalar() or 0
        try:
            await self.bus.publish(rid, ev)
        except Exception as e:  # events are persisted; live delivery failure must not break execution
            log.warning("event_publish_failed", run_id=rid, error=str(e))

    # ------------------------------------------------------------------ node runs
    async def load_node_runs(self, run_id: str) -> dict[tuple[str, str], dict]:
        async with self.session() as s:
            rows = (await s.execute(select(NodeRun).where(NodeRun.run_id == _uuid(run_id)))).scalars().all()
            return {(r.node_id, r.scope): {"id": str(r.id), "status": r.status, "output": r.output, "handle": r.handle,
                                           "error": r.error, "started_at": r.started_at} for r in rows}

    async def node_started(self, run_id: str, node, scope: str, resolved_input: Any, config: Any) -> str:
        async with self.session() as s:
            existing = (await s.execute(select(NodeRun).where(
                NodeRun.run_id == _uuid(run_id), NodeRun.node_id == node.id, NodeRun.scope == scope))).scalar_one_or_none()
            if existing and existing.status == "completed":
                raise RuntimeError("Completed node outputs are immutable")
            if existing is None:
                existing = NodeRun(run_id=_uuid(run_id), node_id=node.id, node_key=node.key, node_type=node.type, scope=scope)
                s.add(existing)
            cfg = node.config or {}
            prior_attempts = list(existing.attempts or [])
            if existing.status in ("running", "failed"):
                prior_attempts.append({"status": "interrupted" if existing.status == "running" else existing.status,
                                       "error": existing.error, "note": "previous execution attempt"})
            existing.status = "running"
            existing.input = redact(resolved_input)
            existing.config = redact(config)
            existing.attempts = prior_attempts
            existing.started_at = utcnow()
            existing.error = None
            await s.commit()
            return str(existing.id)

    async def node_simple(self, run_id: str, node, scope: str, status: str, output: Any = None, handle: str | None = None,
                          error: Any = None) -> str:
        """Records a node that did not execute work (skipped/cancelled/copied from a parent run)."""
        async with self.session() as s:
            nr = (await s.execute(select(NodeRun).where(
                NodeRun.run_id == _uuid(run_id), NodeRun.node_id == node.id, NodeRun.scope == scope))).scalar_one_or_none()
            if nr is None:
                nr = NodeRun(run_id=_uuid(run_id), node_id=node.id, node_key=node.key, node_type=node.type, scope=scope)
                s.add(nr)
            elif nr.status == "completed":
                return str(nr.id)
            nr.status, nr.output, nr.handle, nr.error = status, output, handle, error
            nr.finished_at = utcnow()
            await s.commit()
            return str(nr.id)

    async def node_finished(self, node_run_id: str, status: str, *, output: Any = None, handle: str | None = None,
                            error: Any = None, attempts: list | None = None, usage: dict | None = None,
                            extra_input: dict | None = None) -> None:
        async with self.session() as s:
            nr = await s.get(NodeRun, _uuid(node_run_id))
            nr.status = status
            nr.output = output
            nr.handle = handle
            nr.error = redact(error) if error else None
            if attempts is not None:
                nr.attempts = list(nr.attempts or []) + redact(attempts)
            nr.finished_at = utcnow()
            if nr.started_at:
                start = nr.started_at if nr.started_at.tzinfo else nr.started_at.replace(tzinfo=timezone.utc)
                nr.latency_ms = int((nr.finished_at - start).total_seconds() * 1000)
            if usage:
                for k in ("provider", "model", "fallback_used", "llm_calls", "input_tokens", "output_tokens",
                          "cached_tokens", "cost_usd", "reasoning_summary"):
                    if k in usage and usage[k] is not None:
                        setattr(nr, k, usage[k])
            if extra_input:
                nr.input = {**(nr.input or {}), **redact(extra_input)} if isinstance(nr.input, dict) else nr.input
            await s.commit()

    async def mark_node_waiting(self, node_run_id: str) -> None:
        async with self.session() as s:
            await s.execute(update(NodeRun).where(NodeRun.id == _uuid(node_run_id)).values(status="waiting"))
            await s.commit()

    # ------------------------------------------------------------------ tools & usage
    async def record_tool_run(self, run_id: str, node_run_id: str | None, tool: str, input_: Any, output: Any,
                              success: bool, error: str | None, started: datetime, secrets: list[str]) -> str:
        fin = utcnow()
        async with self.session() as s:
            tr = ToolRun(run_id=_uuid(run_id), node_run_id=_uuid(node_run_id) if node_run_id else None, tool=tool,
                         input=redact(input_, secrets), output=redact(output, secrets), success=success,
                         error=redact(error, secrets) if error else None, started_at=started, finished_at=fin,
                         duration_ms=int((fin - started).total_seconds() * 1000))
            s.add(tr)
            await s.commit()
            return str(tr.id)

    async def record_usage(self, run: dict, node_id: str | None, provider: str, model: str, usage: dict, cost: float | None,
                           purpose: str = "run") -> None:
        async with self.session() as s:
            s.add(UsageRecord(workspace_id=run["workspace_id"], project_id=run.get("project_id"), run_id=run.get("id"),
                              node_id=node_id, provider=provider, model=model, input_tokens=usage.get("input_tokens", 0),
                              output_tokens=usage.get("output_tokens", 0), cached_tokens=usage.get("cached_tokens", 0),
                              cost_usd=cost, purpose=purpose))
            await s.commit()

    # ------------------------------------------------------------------ approvals
    async def create_approval(self, run_id: str, node_id: str, scope: str, cfg: dict, content: Any) -> str:
        async with self.session() as s:
            existing = (await s.execute(select(Approval).where(Approval.run_id == _uuid(run_id), Approval.node_id == node_id,
                                                               Approval.scope == scope))).scalar_one_or_none()
            if existing:
                return str(existing.id)
            a = Approval(run_id=_uuid(run_id), node_id=node_id, scope=scope, title=cfg.get("title") or "Approval required",
                         instructions=cfg.get("instructions") or "", content=content, allow_edit=cfg.get("allow_edit", True))
            s.add(a)
            await s.commit()
            return str(a.id)

    async def get_approval(self, run_id: str, node_id: str, scope: str) -> dict | None:
        async with self.session() as s:
            a = (await s.execute(select(Approval).where(Approval.run_id == _uuid(run_id), Approval.node_id == node_id,
                                                        Approval.scope == scope))).scalar_one_or_none()
            if not a:
                return None
            return {"id": str(a.id), "status": a.status, "content": a.content, "edited_content": a.edited_content,
                    "comment": a.comment, "decided_by": str(a.decided_by) if a.decided_by else None}

    # ------------------------------------------------------------------ memory, secrets, pricing
    async def memory_get(self, workflow_id) -> dict:
        async with self.session() as s:
            rows = (await s.execute(select(WorkflowMemory).where(WorkflowMemory.workflow_id == _uuid(workflow_id)))).scalars().all()
            return {r.key: r.value for r in rows}

    async def memory_set(self, workflow_id, key: str, value: Any) -> None:
        async with self.session() as s:
            row = (await s.execute(select(WorkflowMemory).where(WorkflowMemory.workflow_id == _uuid(workflow_id),
                                                                WorkflowMemory.key == key))).scalar_one_or_none()
            if row:
                row.value = value
            else:
                s.add(WorkflowMemory(workflow_id=_uuid(workflow_id), key=key, value=value))
            await s.commit()

    async def credential(self, workspace_id, credential_id: str | None, provider: str) -> tuple[str | None, str | None]:
        """Returns (api_key, base_url). Looks up by id, else the workspace's first credential for the provider."""
        async with self.session() as s:
            q = select(ProviderCredential).where(ProviderCredential.workspace_id == _uuid(workspace_id))
            if credential_id:
                q = q.where(ProviderCredential.id == _uuid(credential_id))
            else:
                q = q.where(ProviderCredential.provider == provider).order_by(ProviderCredential.created_at)
            c = (await s.execute(q.limit(1))).scalar_one_or_none()
            if c is None:
                return None, None
            return (decrypt_secret(c.encrypted_value) if c.encrypted_value else None), c.base_url

    async def secret_by_name(self, workspace_id, name: str) -> str | None:
        async with self.session() as s:
            c = (await s.execute(select(ProviderCredential).where(
                ProviderCredential.workspace_id == _uuid(workspace_id),
                (ProviderCredential.name == name) | (ProviderCredential.provider == name)).limit(1))).scalar_one_or_none()
            return decrypt_secret(c.encrypted_value) if c and c.encrypted_value else None

    async def pricing(self, provider: str, model: str) -> dict | None:
        async with self.session() as s:
            p = (await s.execute(select(ModelPricing).where(ModelPricing.provider == provider, ModelPricing.model == model,
                                                            ModelPricing.active == True))).scalar_one_or_none()  # noqa: E712
            if not p:
                # Longest-prefix match handles dated model ids (e.g. "gpt-4o-2024-08-06" → "gpt-4o").
                rows = (await s.execute(select(ModelPricing).where(ModelPricing.provider == provider))).scalars().all()
                cands = [r for r in rows if model.startswith(r.model)]
                p = max(cands, key=lambda r: len(r.model)) if cands else None
            if not p:
                return None
            return {"input_per_mtok": p.input_per_mtok, "output_per_mtok": p.output_per_mtok,
                    "cached_input_per_mtok": p.cached_input_per_mtok, "context_window": p.context_window,
                    "capabilities": p.capabilities or {}}
