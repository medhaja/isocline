"""Policy storage helpers: rule validation and effective snapshots for a run's scope chain."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models_v2 import Policy, PolicyRule

RULE_KINDS = ["tool", "model", "model_allowlist", "budget", "approval", "network"]


class RuleIn(BaseModel):
    kind: Literal["tool", "model", "model_allowlist", "budget", "approval", "network"]
    subject: str = Field(default="*", max_length=200)
    action: str = Field(default="*", max_length=32)
    effect: Literal["allow", "deny", "require_approval", "limit"]
    condition: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    mandatory: bool = False

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in ("*", "read", "compute", "write", "external_write", "destructive"):
            raise ValueError("action must be one of *, read, compute, write, external_write, destructive")
        return v

    def check(self) -> None:
        if self.kind == "budget":
            from isocline.engine.policy import BUDGET_KEYS
            if self.subject not in BUDGET_KEYS or self.effect != "limit" or not isinstance(self.value, (int, float)):
                raise ValueError(f"Budget rules need effect 'limit', a numeric value and a subject in {sorted(BUDGET_KEYS)}")
        if self.kind == "model_allowlist" and (not isinstance(self.value, list) or not self.value or self.effect != "allow"):
            raise ValueError("Model allowlists need effect 'allow' and a list of provider/model patterns, e.g. [\"openai/*\"]")
        if self.kind == "approval" and (self.effect != "require_approval" or "metric" not in self.condition):
            raise ValueError("Approval rules need effect 'require_approval' and a metric condition, e.g. projected_cost > 2")
        if self.kind == "tool" and self.effect == "limit":
            raise ValueError("Tool rules allow, deny or require approval")
        allowed = {"agent_template_in", "agent_template_not_in", "node_key_in", "arg", "op", "value", "metric"}
        unknown = set(self.condition) - allowed
        if unknown:
            raise ValueError(f"Unknown condition keys {sorted(unknown)}")


async def snapshot(db: AsyncSession, *, workspace_id, project_id=None, workflow_id=None) -> list[dict]:
    scopes = [("workspace", workspace_id), ("project", project_id), ("workflow", workflow_id)]
    conds = [(Policy.scope_type == t) & (Policy.scope_id == i) for t, i in scopes if i]
    if not conds:
        return []
    rows = (await db.execute(select(Policy, PolicyRule).join(PolicyRule, PolicyRule.policy_id == Policy.id)
                             .where(Policy.workspace_id == workspace_id, Policy.enabled == True, or_(*conds))  # noqa: E712
                             .order_by(Policy.scope_type, PolicyRule.position))).all()
    return [{"id": str(r.id), "policy_id": str(p.id), "policy_name": p.name, "policy_version": p.version,
             "scope_type": p.scope_type, "kind": r.kind, "subject": r.subject, "action": r.action, "effect": r.effect,
             "condition": r.condition or {}, "value": r.value, "mandatory": r.mandatory} for p, r in rows]
