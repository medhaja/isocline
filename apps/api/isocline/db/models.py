"""Relational data model. JSONB is used only for flexible node/graph configuration and payloads."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

try:  # pgvector is only needed on PostgreSQL; the desktop build (SQLite) ships without it.
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - exercised by the desktop build
    Vector = None
from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
    UniqueConstraint, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from isocline.core.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")
EMBED_DIM = get_settings().embedding_dim


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------------------------------------------------------------- identity & tenancy
class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthToken(Base, TimestampMixin):
    __tablename__ = "auth_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # password_reset | email_verify
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)


class WorkspaceMember(Base, TimestampMixin):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(64), default="owner")  # owner | admin | developer | operator | reviewer | viewer


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- workflows
class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | published | archived
    graph: Mapped[dict] = mapped_column(JSONType, default=dict)  # working draft
    revision: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency for autosave
    latest_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkflowVersion(Base, TimestampMixin):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict] = mapped_column(JSONType)  # immutable snapshot
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class WorkflowMemory(Base):
    __tablename__ = "workflow_memory"
    __table_args__ = (UniqueConstraint("workflow_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- agents
class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(16), default="")
    config: Mapped[dict] = mapped_column(JSONType)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String(64), default="custom")
    config: Mapped[dict] = mapped_column(JSONType)  # AgentConfig
    slug: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # stable, human-readable reference
    draft_contract: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- providers & secrets
class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # openai | anthropic | ...
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(64))
    default_base_url: Mapped[str | None] = mapped_column(String(500))
    requires_key: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelPricing(Base):
    """Server-side model metadata + pricing. Updateable at runtime via the admin API."""
    __tablename__ = "model_pricing"
    __table_args__ = (UniqueConstraint("provider", "model"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    context_window: Mapped[int | None] = mapped_column(Integer)
    input_per_mtok: Mapped[float | None] = mapped_column(Float)
    output_per_mtok: Mapped[float | None] = mapped_column(Float)
    cached_input_per_mtok: Mapped[float | None] = mapped_column(Float)
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderCredential(Base, TimestampMixin):
    __tablename__ = "provider_credentials"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))  # provider id or "custom"/"search"
    name: Mapped[str] = mapped_column(String(200))
    encrypted_value: Mapped[bytes | None] = mapped_column(LargeBinary)
    hint: Mapped[str] = mapped_column(String(16), default="")  # last 4 chars
    base_url: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------- knowledge
class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=150)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | processing | ready | failed
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM).with_variant(JSON(), "sqlite") if Vector is not None else JSON())
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)


# ---------------------------------------------------------------- execution
class Run(Base, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("workflow_id", "idempotency_key", name="uq_run_idempotency"),
        Index("ix_runs_status_heartbeat", "status", "heartbeat_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_versions.id"))
    graph_snapshot: Mapped[dict] = mapped_column(JSONType)  # exact graph executed
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # effective, clamped limits
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    input: Mapped[Any] = mapped_column(JSONType, default=dict)
    output: Mapped[Any] = mapped_column(JSONType, nullable=True)
    error: Mapped[Any] = mapped_column(JSONType, nullable=True)
    trigger: Mapped[str] = mapped_column(String(16), default="ui")  # ui | api | eval | replay
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    replay_from_node_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(200))
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)
    # V2
    execution_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True)
    checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("checkpoints.id", ondelete="SET NULL"), nullable=True)
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("triggers.id", ondelete="SET NULL"), nullable=True)
    parent_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sub-workflow call site in parent_run


class NodeRun(Base):
    __tablename__ = "node_runs"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "scope", name="uq_node_run_scope"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    node_key: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)  # library agent attribution
    node_type: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(200), default="")  # "" top-level; "loop1#2" inside a loop iteration
    status: Mapped[str] = mapped_column(String(16), default="queued")
    input: Mapped[Any] = mapped_column(JSONType, nullable=True)  # resolved input/context
    config: Mapped[Any] = mapped_column(JSONType, nullable=True)  # effective config used
    output: Mapped[Any] = mapped_column(JSONType, nullable=True)  # immutable once completed
    handle: Mapped[str | None] = mapped_column(String(64))  # branch taken
    error: Mapped[Any] = mapped_column(JSONType, nullable=True)
    attempts: Mapped[list] = mapped_column(JSONType, default=list)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # V2: cache + routing observability
    cache_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # hit | miss | stored | bypass
    saved_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    saved_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ToolRun(Base):
    __tablename__ = "tool_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("node_runs.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    input: Mapped[Any] = mapped_column(JSONType, nullable=True)
    output: Mapped[Any] = mapped_column(JSONType, nullable=True)  # sanitized
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    title: Mapped[str] = mapped_column(String(300), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[Any] = mapped_column(JSONType, nullable=True)
    allow_edit: Mapped[bool] = mapped_column(Boolean, default=True)
    edited_content: Mapped[Any] = mapped_column(JSONType, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # V2: approvals raised by policies/recovery (not only HITL nodes)
    kind: Mapped[str] = mapped_column(String(24), default="node")  # node | tool_call | run_budget | recovery
    subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------- evaluation
class EvaluationDataset(Base, TimestampMixin):
    __tablename__ = "evaluation_datasets"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    cases: Mapped[list["EvaluationCase"]] = relationship(back_populates="dataset", cascade="all, delete-orphan", order_by="EvaluationCase.created_at")


class EvaluationCase(Base, TimestampMixin):
    __tablename__ = "evaluation_cases"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    input: Mapped[Any] = mapped_column(JSONType, default=dict)
    expected: Mapped[Any] = mapped_column(JSONType, nullable=True)
    evaluators: Mapped[list] = mapped_column(JSONType, default=list)  # [{type, ...config}]
    dataset: Mapped[EvaluationDataset] = relationship(back_populates="cases")


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_versions.id"))
    status: Mapped[str] = mapped_column(String(16), default="running")
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # V2: experiments/optimizer/CI evaluate an explicit graph (candidate) instead of the draft/version
    graph: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)


class EvaluationResult(Base, TimestampMixin):
    __tablename__ = "evaluation_results"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | passed | failed | error
    scores: Mapped[list] = mapped_column(JSONType, default=list)


# ---------------------------------------------------------------- accounting & audit
class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), index=True)
    node_id: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    purpose: Mapped[str] = mapped_column(String(32), default="run")  # run | assistant | generator | eval_judge


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


# Harness tables live in models_v2 (imported so they share this metadata).
from isocline.db import models_v2  # noqa: E402,F401
from isocline.db import immutability  # noqa: E402,F401  (append-only audit log guard)

V1_TABLES = ["users", "auth_tokens", "workspaces", "workspace_members", "projects", "workflows", "workflow_versions",
             "workflow_memory", "agent_templates", "agents", "providers", "model_pricing", "provider_credentials",
             "knowledge_bases", "documents", "document_chunks", "runs", "node_runs", "tool_runs", "run_events", "approvals",
             "evaluation_datasets", "evaluation_cases", "evaluation_runs", "evaluation_results",
             "usage_records", "audit_events"]
