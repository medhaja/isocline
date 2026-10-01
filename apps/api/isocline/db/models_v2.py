"""Isocline V2 data model: contracts & types, artifacts, policies, planning, checkpoints, cache, recovery,
experiments, component tests, optimizer, monitoring, triggers, durable waits,
goal plans, MCP, quotas and personal access tokens.

Normalized where rows are queried/filtered (rules, releases, gates, waits, cache keys); JSON only for payloads."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from isocline.db.models import Base, JSONType, TimestampMixin, new_id, utcnow


def _fk(target: str, ondelete: str = "CASCADE", nullable: bool = False, index: bool = True):
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)


# ======================================================================= contracts & types
class CustomType(Base, TimestampMixin):
    """User-defined JSON Schema types usable in contracts as JSON<Name>."""
    __tablename__ = "custom_types"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_custom_type_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    json_schema: Mapped[dict] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentContract(Base, TimestampMixin):
    """Versioned contract of a library agent (workflow-embedded agents carry their contract in the node)."""
    __tablename__ = "agent_contracts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    agent_id: Mapped[uuid.UUID] = _fk("agents.id")
    version: Mapped[int] = mapped_column(Integer, default=1)
    contract: Mapped[dict] = mapped_column(JSONType)


# ======================================================================= artifacts
class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_project_created", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    workflow_id: Mapped[uuid.UUID | None] = _fk("workflows.id", "SET NULL", True)
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", "SET NULL", True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32), index=True)  # csv | json | pdf | image | text | code | zip | report | table | other
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(64))  # sha256
    storage_key: Mapped[str] = mapped_column(String(500))  # internal; never exposed
    transformation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)


class ArtifactLineage(Base, TimestampMixin):
    __tablename__ = "artifact_lineage"
    __table_args__ = (UniqueConstraint("artifact_id", "parent_artifact_id", name="uq_artifact_parent"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    artifact_id: Mapped[uuid.UUID] = _fk("artifacts.id")
    parent_artifact_id: Mapped[uuid.UUID] = _fk("artifacts.id")
    transformation: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ArtifactUsage(Base, TimestampMixin):
    """Which node runs consumed an artifact (producer is on the artifact row)."""
    __tablename__ = "artifact_usages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    artifact_id: Mapped[uuid.UUID] = _fk("artifacts.id")
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    node_id: Mapped[str] = mapped_column(String(64))
    node_key: Mapped[str] = mapped_column(String(64))


# ======================================================================= model intelligence
class ModelRoutingDecision(Base, TimestampMixin):
    __tablename__ = "model_routing_decisions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", "CASCADE", True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[str] = mapped_column(String(200), default="")
    objective: Mapped[str] = mapped_column(String(16))
    selected_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reasons: Mapped[list] = mapped_column(JSONType, default=list)
    candidates: Mapped[list] = mapped_column(JSONType, default=list)  # scored + rejected with reasons


# ======================================================================= policy engine
class Policy(Base, TimestampMixin):
    __tablename__ = "policies"
    __table_args__ = (Index("ix_policies_scope", "scope_type", "scope_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    scope_type: Mapped[str] = mapped_column(String(16))  # workspace | project | workflow
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PolicyRule(Base, TimestampMixin):
    __tablename__ = "policy_rules"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    policy_id: Mapped[uuid.UUID] = _fk("policies.id")
    kind: Mapped[str] = mapped_column(String(24))  # tool | model_allowlist | budget | approval | network
    subject: Mapped[str] = mapped_column(String(200), default="*")  # tool name, mcp:server/tool, provider/model glob, metric
    action: Mapped[str] = mapped_column(String(32), default="*")  # read | write | external_write | destructive | *
    effect: Mapped[str] = mapped_column(String(24))  # allow | deny | require_approval | limit
    condition: Mapped[dict] = mapped_column(JSONType, default=dict)
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class PolicyDecision(Base, TimestampMixin):
    __tablename__ = "policy_decisions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID | None] = _fk("runs.id", "CASCADE", True)
    workspace_id: Mapped[uuid.UUID | None] = _fk("workspaces.id", "CASCADE", True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    subject: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(32))
    effect: Mapped[str] = mapped_column(String(24))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict] = mapped_column(JSONType, default=dict)


# ======================================================================= planning, checkpoints, cache, recovery
class ExecutionPlan(Base, TimestampMixin):
    __tablename__ = "execution_plans"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id")
    graph_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # READY | BLOCKED
    plan: Mapped[dict] = mapped_column(JSONType)


class Checkpoint(Base, TimestampMixin):
    __tablename__ = "checkpoints"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    node_id: Mapped[str] = mapped_column(String(64))
    node_key: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(40))  # after_expensive | before_approval | before_side_effect | subworkflow | user
    completed_node_runs: Mapped[list] = mapped_column(JSONType)  # node_run ids complete at this point
    artifact_ids: Mapped[list] = mapped_column(JSONType, default=list)
    state: Mapped[dict] = mapped_column(JSONType, default=dict)  # totals, variables, config versions


class CacheEntry(Base, TimestampMixin):
    __tablename__ = "cache_entries"
    __table_args__ = (Index("ix_cache_lookup", "workspace_id", "cache_key"), Index("ix_cache_signature", "workspace_id", "signature"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id", index=False)
    cache_key: Mapped[str] = mapped_column(String(64))  # exact identity
    signature: Mapped[str] = mapped_column(String(64))  # identity minus the request text (for semantic lookup)
    node_type: Mapped[str] = mapped_column(String(32))
    key_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    output: Mapped[Any] = mapped_column(JSONType, nullable=True)
    usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_node_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompensationAction(Base, TimestampMixin):
    __tablename__ = "compensation_actions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    node_id: Mapped[str] = mapped_column(String(64))
    node_key: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    performed: Mapped[dict] = mapped_column(JSONType)  # summary of the side effect
    compensation: Mapped[dict] = mapped_column(JSONType)  # resolved compensating action
    status: Mapped[str] = mapped_column(String(16), default="available")  # available | attempted | succeeded | failed | skipped
    result: Mapped[Any] = mapped_column(JSONType, nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # user id or "policy"


# ======================================================================= experiments & component tests
class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_id: Mapped[uuid.UUID] = _fk("evaluation_datasets.id")
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | running | completed
    base_graph: Mapped[dict] = mapped_column(JSONType)


class ExperimentVariant(Base, TimestampMixin):
    __tablename__ = "experiment_variants"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    experiment_id: Mapped[uuid.UUID] = _fk("experiments.id")
    name: Mapped[str] = mapped_column(String(120))
    overrides: Mapped[dict] = mapped_column(JSONType)  # {model, prompt, params, context, knowledge_base_ids, tools}
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)


class ComponentTest(Base, TimestampMixin):
    __tablename__ = "component_tests"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id")
    node_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    run_input: Mapped[Any] = mapped_column(JSONType, default=dict)
    mocks: Mapped[dict] = mapped_column(JSONType, default=dict)  # upstream node key -> mocked output
    assertions: Mapped[list] = mapped_column(JSONType, default=list)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # passed | failed | error | running
    last_graph_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_details: Mapped[list] = mapped_column(JSONType, default=list)


# ======================================================================= optimizer & monitoring
class OptimizationRun(Base, TimestampMixin):
    __tablename__ = "optimization_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id")
    base_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="analyzed")  # analyzed | candidate | evaluating | evaluated | applied
    current_metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    projected_metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    candidate_graph: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    baseline_eval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    candidate_eval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class OptimizationRecommendation(Base, TimestampMixin):
    __tablename__ = "optimization_recommendations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    optimization_run_id: Mapped[uuid.UUID] = _fk("optimization_runs.id")
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    operations: Mapped[list] = mapped_column(JSONType, default=list)  # graph patch (same ops as the assistant)
    impact: Mapped[dict] = mapped_column(JSONType, default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)


class DriftEvent(Base, TimestampMixin):
    __tablename__ = "drift_events"
    __table_args__ = (Index("ix_drift_workflow", "workflow_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id", index=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    metric: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(12))  # info | warning | critical
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    current: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    primary_node_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    day: Mapped[str] = mapped_column(String(10))  # dedupe key YYYY-MM-DD
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ======================================================================= triggers & durable waits
class Trigger(Base, TimestampMixin):
    __tablename__ = "triggers"
    __table_args__ = (Index("ix_triggers_due", "kind", "enabled", "next_run_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    workflow_id: Mapped[uuid.UUID] = _fk("workflows.id")
    kind: Mapped[str] = mapped_column(String(16))  # webhook | schedule | event | file
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_id: Mapped[str | None] = mapped_column(String(48), unique=True, nullable=True)  # webhook path id
    secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)  # cron, timezone, auth, payload schema, event name, input mapping
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class TriggerDelivery(Base, TimestampMixin):
    """Replay protection + idempotency for webhook/event deliveries."""
    __tablename__ = "trigger_deliveries"
    __table_args__ = (UniqueConstraint("trigger_id", "dedupe_key", name="uq_trigger_delivery"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    trigger_id: Mapped[uuid.UUID] = _fk("triggers.id")
    dedupe_key: Mapped[str] = mapped_column(String(200))
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="accepted")


class WaitState(Base, TimestampMixin):
    """Durable waits. A waiting run holds no worker; resumption is driven from these rows."""
    __tablename__ = "wait_states"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "scope", name="uq_wait_node"),
                      Index("ix_wait_due", "status", "resume_at"), Index("ix_wait_timeout", "status", "timeout_at"),
                      Index("ix_wait_event", "status", "event_name", "correlation_key"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = _fk("runs.id", index=False)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    node_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(16))  # approval | timer | webhook | event | subworkflow
    status: Mapped[str] = mapped_column(String(16), default="waiting")  # waiting | resumed | timed_out | cancelled
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_action: Mapped[str] = mapped_column(String(16), default="edge")  # edge | fail | continue
    callback_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    event_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    child_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[Any] = mapped_column(JSONType, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ======================================================================= goal mode
class GoalPlan(Base, TimestampMixin):
    __tablename__ = "goal_plans"
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_goal_plan_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))  # model | heuristic
    plan: Mapped[dict] = mapped_column(JSONType)  # planner output (steps)
    graph: Mapped[dict] = mapped_column(JSONType)  # validated graph executed
    validation: Mapped[list] = mapped_column(JSONType, default=list)


# ======================================================================= MCP, quotas, tokens
class McpServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_mcp_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(64))  # slug used in tool ids: mcp:<name>/<tool>
    transport: Mapped[str] = mapped_column(String(24), default="streamable_http")
    endpoint: Mapped[str] = mapped_column(String(500))
    credential_id: Mapped[uuid.UUID | None] = _fk("provider_credentials.id", "SET NULL", True, False)
    allowed_tools: Mapped[list] = mapped_column(JSONType, default=list)  # explicit allowlist; [] = none
    tools: Mapped[list] = mapped_column(JSONType, default=list)  # last synced tool definitions
    status: Mapped[str] = mapped_column(String(16), default="unsynced")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceQuota(Base, TimestampMixin):
    __tablename__ = "workspace_quotas"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=10)
    max_concurrent_nodes: Mapped[int] = mapped_column(Integer, default=20)
    monthly_token_quota: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_cost_quota: Mapped[float | None] = mapped_column(Float, nullable=True)
    sandbox_concurrency: Mapped[int] = mapped_column(Integer, default=4)
    artifact_storage_bytes: Mapped[int] = mapped_column(BigInteger, default=5 * 1024 ** 3)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=600)


class PersonalAccessToken(Base, TimestampMixin):
    __tablename__ = "personal_access_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
