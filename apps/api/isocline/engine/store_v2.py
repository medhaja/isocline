"""Persistence for V2 harness state (cache, policy decisions, routing decisions, checkpoints, durable waits,
tool-call approvals, compensation, artifacts, sub-workflow runs). Mixed into SqlRunStore."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from isocline.core.logging import redact
from isocline.db.models import Approval, Document, NodeRun, Run, utcnow
from isocline.db.models_v2 import (
    CacheEntry, Checkpoint, CompensationAction, GoalPlan, ModelRoutingDecision, PolicyDecision, WaitState,
)


def _u(v) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        from datetime import timezone
        return d.replace(tzinfo=timezone.utc)
    return d


class HarnessStoreMixin:
    # ------------------------------------------------------------------ cache
    async def cache_lookup(self, workspace_id, key: str) -> dict | None:
        async with self.session() as s:
            e = (await s.execute(select(CacheEntry).where(CacheEntry.workspace_id == _u(workspace_id), CacheEntry.cache_key == key)
                                 .order_by(CacheEntry.created_at.desc()).limit(1))).scalar_one_or_none()
            if e is None or _aware(e.expires_at) <= utcnow():
                return None
            e.hits += 1
            await s.commit()
            return self._cache_dict(e, 1.0)

    async def cache_semantic(self, workspace_id, signature: str, embedding: list[float], threshold: float) -> dict | None:
        from isocline.services.embeddings import cosine
        async with self.session() as s:
            rows = (await s.execute(select(CacheEntry).where(CacheEntry.workspace_id == _u(workspace_id), CacheEntry.signature == signature,
                                                             CacheEntry.expires_at > utcnow()).order_by(CacheEntry.created_at.desc()).limit(200))).scalars().all()
            best, score = None, 0.0
            for e in rows:
                if not e.embedding:
                    continue
                sim = cosine(embedding, e.embedding)
                if sim > score:
                    best, score = e, sim
            if best is None or score < threshold:
                return None
            best.hits += 1
            await s.commit()
            return self._cache_dict(best, score)

    @staticmethod
    def _cache_dict(e: CacheEntry, similarity: float) -> dict:
        return {"id": str(e.id), "output": e.output, "usage": e.usage, "source_run_id": str(e.source_run_id) if e.source_run_id else None,
                "source_node_run_id": str(e.source_node_run_id) if e.source_node_run_id else None, "cost_usd": e.cost_usd,
                "latency_ms": e.latency_ms, "created_at": _aware(e.created_at).isoformat(), "similarity": round(similarity, 4),
                "age_seconds": int((utcnow() - _aware(e.created_at)).total_seconds())}

    async def cache_store(self, workspace_id, *, key: str, signature: str, node_type: str, key_text: str, embedding, output,
                          usage: dict, run_id, node_run_id, cost: float, latency_ms: int, ttl_seconds: int) -> None:
        async with self.session() as s:
            s.add(CacheEntry(workspace_id=_u(workspace_id), cache_key=key, signature=signature, node_type=node_type,
                             key_text=key_text[:20000], embedding=embedding, output=output, usage=usage, source_run_id=_u(run_id),
                             source_node_run_id=_u(node_run_id), cost_usd=cost or 0.0, latency_ms=latency_ms or 0,
                             expires_at=utcnow() + timedelta(seconds=ttl_seconds)))
            await s.commit()

    async def mark_cache(self, node_run_id: str, status: str, saved_cost: float | None = None, saved_ms: int | None = None) -> None:
        async with self.session() as s:
            await s.execute(update(NodeRun).where(NodeRun.id == _u(node_run_id)).values(cache_status=status, saved_cost_usd=saved_cost, saved_ms=saved_ms))
            await s.commit()

    async def kb_versions(self, kb_ids: list[str]) -> dict:
        if not kb_ids:
            return {}
        async with self.session() as s:
            rows = (await s.execute(select(Document.knowledge_base_id, func.count(Document.id), func.max(Document.created_at))
                                    .where(Document.knowledge_base_id.in_([_u(k) for k in kb_ids]), Document.status == "ready")
                                    .group_by(Document.knowledge_base_id))).all()
            return {str(k): [n, str(m)] for k, n, m in rows}

    async def routing_candidates(self, workspace_id):
        from isocline.services.model_intel import load_candidates
        async with self.session() as s:
            return await load_candidates(s, _u(workspace_id))

    async def load_mcp_servers(self, workspace_id) -> dict[str, dict]:
        from isocline.db.models_v2 import McpServer
        async with self.session() as s:
            rows = (await s.execute(select(McpServer).where(McpServer.workspace_id == _u(workspace_id)))).scalars().all()
            return {r.name: {"id": str(r.id), "endpoint": r.endpoint, "credential_id": str(r.credential_id) if r.credential_id else None,
                             "allowed_tools": list(r.allowed_tools or []), "tools": list(r.tools or []),
                             "rate_limit_per_minute": r.rate_limit_per_minute} for r in rows}

    # ------------------------------------------------------------------ decisions
    async def record_policy_decision(self, run: dict, node_id: str | None, kind: str, subject: str, action: str, decision, context: dict) -> None:
        async with self.session() as s:
            s.add(PolicyDecision(run_id=_u(run["id"]), workspace_id=_u(run["workspace_id"]), node_id=node_id, kind=kind, subject=subject,
                                 action=action, effect=decision.effect, rule_id=_u(decision.rule_id) if _is_uuid(decision.rule_id) else None,
                                 policy_id=_u(decision.policy_id) if _is_uuid(decision.policy_id) else None,
                                 reason=decision.reason, context=redact(context)))
            await s.commit()

    async def record_routing(self, run_id, node_id: str, scope: str, objective: str, decision) -> str:
        async with self.session() as s:
            d = ModelRoutingDecision(run_id=_u(run_id), node_id=node_id, scope=scope, objective=objective,
                                     selected_provider=decision.provider, selected_model=decision.model,
                                     reasons=decision.reasons, candidates=decision.candidates)
            s.add(d)
            await s.commit()
            return str(d.id)

    # ------------------------------------------------------------------ checkpoints
    async def create_checkpoint(self, run: dict, node, reason: str, totals: dict) -> str:
        async with self.session() as s:
            done = (await s.execute(select(NodeRun.id).where(NodeRun.run_id == _u(run["id"]), NodeRun.status.in_(("completed", "skipped")),
                                                             NodeRun.scope == ""))).scalars().all()
            from isocline.db.models_v2 import Artifact
            arts = (await s.execute(select(Artifact.id).where(Artifact.run_id == _u(run["id"])))).scalars().all()
            cp = Checkpoint(run_id=_u(run["id"]), node_id=node.id, node_key=node.key, reason=reason,
                            completed_node_runs=[str(x) for x in done], artifact_ids=[str(a) for a in arts],
                            state={"totals": totals, "variables": (run.get("graph_snapshot") or {}).get("settings", {}).get("variables", {}),
                                   "workflow_version_id": str(run["workflow_version_id"]) if run.get("workflow_version_id") else None})
            s.add(cp)
            await s.commit()
            return str(cp.id)

    # ------------------------------------------------------------------ durable waits
    async def create_wait(self, run: dict, node_id: str, scope: str, kind: str, *, resume_at=None, timeout_at=None,
                          timeout_action: str = "edge", event_name: str | None = None, correlation_key: str | None = None,
                          child_run_id=None) -> dict:
        async with self.session() as s:
            w = (await s.execute(select(WaitState).where(WaitState.run_id == _u(run["id"]), WaitState.node_id == node_id,
                                                         WaitState.scope == scope))).scalar_one_or_none()
            token = None
            if w is None:
                w = WaitState(run_id=_u(run["id"]), workspace_id=_u(run["workspace_id"]), node_id=node_id, scope=scope, kind=kind,
                              resume_at=resume_at, timeout_at=timeout_at, timeout_action=timeout_action, event_name=event_name,
                              correlation_key=correlation_key, child_run_id=_u(child_run_id) if child_run_id else None,
                              callback_token_hash=hashlib.sha256(token.encode()).hexdigest() if token else None)
                s.add(w)
                await s.commit()
            return {"id": str(w.id), "status": w.status, "payload": w.payload, "token": token, "kind": w.kind}

    async def get_wait(self, run_id, node_id: str, scope: str) -> dict | None:
        async with self.session() as s:
            w = (await s.execute(select(WaitState).where(WaitState.run_id == _u(run_id), WaitState.node_id == node_id,
                                                         WaitState.scope == scope))).scalar_one_or_none()
            if not w:
                return None
            return {"id": str(w.id), "status": w.status, "payload": w.payload, "kind": w.kind, "timeout_action": w.timeout_action,
                    "child_run_id": str(w.child_run_id) if w.child_run_id else None}


    # ------------------------------------------------------------------ sub-workflows
    async def start_child_run(self, parent: dict, node, scope: str, workflow_id: str, version: int | None, child_input, budget) -> str:
        """Creates the child run for a sub-workflow node. The child gets the parent's *remaining* budget."""
        from isocline.db.models import Workflow, WorkflowVersion
        depth = int((parent.get("settings") or {}).get("_depth") or 0) + 1
        if depth > 5:
            raise ValueError("Sub-workflows are nested more than 5 levels deep")
        async with self.session() as s:
            try:
                wf = await s.get(Workflow, _u(workflow_id))
            except ValueError:
                wf = None
            if wf is None:
                raise ValueError("Sub-workflow not found")
            from isocline.db.models import Project
            proj = await s.get(Project, wf.project_id)
            if proj is None or proj.workspace_id != _u(parent["workspace_id"]):
                raise ValueError("Sub-workflow belongs to another workspace")
            q = select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id)
            q = q.where(WorkflowVersion.version == version) if version else q.order_by(WorkflowVersion.version.desc())
            v = (await s.execute(q.limit(1))).scalar_one_or_none()
            if v is None:
                raise ValueError("Sub-workflows must reference a published version")
            ps = parent.get("settings") or {}
            settings = dict(v.graph.get("settings") or {})
            from isocline.engine.budget import effective_settings
            settings = effective_settings(settings)
            remaining_cost = None if ps.get("max_cost") is None else max(0.0, float(ps["max_cost"]) - budget.cost)
            settings["max_cost"] = remaining_cost if settings.get("max_cost") is None else min(settings["max_cost"], remaining_cost if remaining_cost is not None else settings["max_cost"])
            settings["max_llm_calls"] = max(1, min(settings["max_llm_calls"], ps.get("max_llm_calls", 50) - budget.llm_calls))
            settings["max_tool_calls"] = max(0, min(settings["max_tool_calls"], ps.get("max_tool_calls", 100) - budget.tool_calls))
            settings["max_runtime_seconds"] = max(5, min(settings["max_runtime_seconds"], int(budget.remaining_runtime())))
            for k in ("_policy", "_custom_types", "_sandbox_concurrency", "_summarizer"):
                if k in ps:
                    settings[k] = ps[k]
            settings.update({"_depth": depth, "_parent_scope": scope})
            child = Run(workspace_id=_u(parent["workspace_id"]), project_id=wf.project_id, workflow_id=wf.id, workflow_version_id=v.id,
                        graph_snapshot=v.graph, settings=settings, status="queued", input=child_input, trigger="subworkflow",
                        parent_run_id=_u(parent["id"]), parent_node_id=node.id)
            s.add(child)
            await s.commit()
            return str(child.id)

    async def resolve_parent_wait(self, child: dict, status: str, output, error, totals: dict) -> str | None:
        """Called when a sub-workflow child finishes: resumes the waiting parent node. Returns the parent run id."""
        if not child.get("parent_node_id") or not child.get("parent_run_id"):
            return None
        scope = (child.get("settings") or {}).get("_parent_scope", "")
        async with self.session() as s:
            w = (await s.execute(select(WaitState).where(WaitState.run_id == _u(child["parent_run_id"]), WaitState.node_id == child["parent_node_id"],
                                                         WaitState.scope == scope, WaitState.kind == "subworkflow"))).scalar_one_or_none()
            if w is None or w.status != "waiting":
                return None
            w.status, w.resolved_at = "resumed", utcnow()
            w.payload = {"status": status, "output": output, "error": error, "totals": totals, "child_run_id": str(child["id"])}
            await s.execute(update(Run).where(Run.id == w.run_id, Run.status == "waiting").values(status="resuming", heartbeat_at=utcnow()))
            await s.commit()
            return str(w.run_id)

    # ------------------------------------------------------------------ tool-call approvals (policy interception)
    async def tool_approval(self, run_id, node_id: str, scope: str, subject_hash: str) -> dict | None:
        async with self.session() as s:
            a = (await s.execute(select(Approval).where(Approval.run_id == _u(run_id), Approval.node_id == node_id, Approval.scope == scope,
                                                        Approval.subject_hash == subject_hash))).scalar_one_or_none()
            return {"id": str(a.id), "status": a.status, "comment": a.comment, "decided_by": str(a.decided_by) if a.decided_by else None,
                    "decided_at": a.decided_at.isoformat() if a.decided_at else None, "edited_content": a.edited_content} if a else None

    async def request_tool_approval(self, run_id, node_id: str, scope: str, subject_hash: str, title: str, content: Any,
                                    kind: str = "tool_call") -> str:
        async with self.session() as s:
            existing = (await s.execute(select(Approval).where(Approval.run_id == _u(run_id), Approval.node_id == node_id, Approval.scope == scope,
                                                               Approval.subject_hash == subject_hash))).scalar_one_or_none()
            if existing:
                return str(existing.id)
            a = Approval(run_id=_u(run_id), node_id=node_id, scope=scope, title=title, content=redact(content), allow_edit=False,
                         kind=kind, subject_hash=subject_hash,
                         instructions="Approve to let the harness perform this action once. Reject to deny it; the agent is told it was denied.")
            s.add(a)
            await s.commit()
            return str(a.id)

    async def pending_policy_approvals(self, run_id, node_id: str, scope: str) -> list[dict]:
        async with self.session() as s:
            rows = (await s.execute(select(Approval).where(Approval.run_id == _u(run_id), Approval.node_id == node_id, Approval.scope == scope,
                                                           Approval.kind != "node"))).scalars().all()
            return [{"id": str(a.id), "status": a.status, "kind": a.kind, "subject_hash": a.subject_hash} for a in rows]

    # ------------------------------------------------------------------ compensation
    async def record_compensation(self, run_id, node, performed: dict, compensation: dict) -> None:
        async with self.session() as s:
            n = (await s.execute(select(func.count(CompensationAction.id)).where(CompensationAction.run_id == _u(run_id)))).scalar() or 0
            s.add(CompensationAction(run_id=_u(run_id), node_id=node.id, node_key=node.key, sequence=n + 1,
                                     performed=redact(performed), compensation=compensation))
            await s.commit()

    # ------------------------------------------------------------------ goal plans
    async def save_goal_plan(self, run_id, version: int, reason: str, method: str, plan: dict, graph: dict, validation: list) -> None:
        async with self.session() as s:
            s.add(GoalPlan(run_id=_u(run_id), version=version, reason=reason, method=method, plan=plan, graph=graph, validation=validation))
            await s.execute(update(Run).where(Run.id == _u(run_id)).values(graph_snapshot=graph))
            await s.commit()

    async def goal_plan_count(self, run_id) -> int:
        async with self.session() as s:
            return (await s.execute(select(func.count(GoalPlan.id)).where(GoalPlan.run_id == _u(run_id)))).scalar() or 0


def _is_uuid(v) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False
