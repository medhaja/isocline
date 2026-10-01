"""Isocline workflow schema v2.0 (reads and upgrades v1.0 documents).

This is the ONLY persistent workflow representation. Manually built, imported and AI-generated
workflows all validate against these models. Nothing here depends on React Flow, LangGraph,
CrewAI or AutoGen.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "2.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "2.0"}  # 1.0 documents are upgraded in memory; untyped edges become Any

INPUT_TYPES = {"input_text", "input_json", "input_file", "input_url", "input_chat"}
AGENT_TYPES = {"agent"}
LOGIC_TYPES = {"condition", "router", "parallel", "merge", "loop", "retry", "transform", "human_approval"}
TOOL_TYPES = {
    "tool_web_search", "tool_http", "tool_python", "tool_calculator",
    "tool_file_reader", "tool_json", "tool_vector_search",
}
OUTPUT_TYPES = {"output_text", "output_json", "output_file", "output_report", "output_api"}
ANNOTATION_TYPES = {"group", "note"}  # visual only; never executed
# V2
TRIGGER_TYPES = {"trigger_webhook", "trigger_schedule", "trigger_event", "trigger_file"}  # entry points
WAIT_TYPES = {"wait_timer", "wait_webhook", "wait_event"}  # durable waits (hold no worker)
COMPOSITE_TYPES = {"subworkflow"}  # pinned published workflow version
ENTRY_TYPES = INPUT_TYPES | TRIGGER_TYPES
NODE_TYPES = (INPUT_TYPES | AGENT_TYPES | LOGIC_TYPES | TOOL_TYPES | OUTPUT_TYPES | ANNOTATION_TYPES
              | TRIGGER_TYPES | WAIT_TYPES | COMPOSITE_TYPES)

AGENT_TEMPLATES = [
    "general", "research", "financial_analyst", "data_analyst", "python", "developer",
    "product_manager", "technical_product_manager", "planner", "manager", "reviewer",
    "critic", "writer", "summarizer", "custom",
]
TOOL_NAMES = ["web_search", "http_request", "python", "calculator", "file_reader", "json_processor", "vector_search",
              "read_artifact"]
MCP_TOOL_RE = re.compile(r"^mcp:[a-z0-9][a-z0-9_-]{0,63}/[A-Za-z0-9_.\-]{1,128}$")
OPERATORS = ["==", "!=", ">", ">=", "<", "<=", "contains", "exists", "not_exists"]
ON_FAILURE = ["stop", "continue", "skip", "route_error"]

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
RESERVED_KEYS = {"input", "vars", "loop", "memory", "run", "upstream", "env", "secrets"}


class Position(BaseModel):
    x: float = 0
    y: float = 0


class ModelParams(BaseModel):
    """Only parameters supported by the selected model are sent; see providers.capabilities."""
    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    seed: int | None = None
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    stop: list[str] | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class ModelRef(BaseModel):
    provider: str = ""  # "auto" lets the harness router choose
    model: str = ""
    credential_id: str | None = None

    @property
    def is_auto(self) -> bool:
        return self.provider == "auto"


class RoutingConfig(BaseModel):
    """Constraints for AUTO model selection (enforced by the router, recorded per decision)."""
    objective: Literal["quality", "cost", "latency", "balanced"] = "balanced"
    allowed_providers: list[str] = Field(default_factory=list)  # empty = any configured provider
    max_cost_per_call: float | None = Field(default=None, ge=0)
    max_latency_seconds: float | None = Field(default=None, gt=0)
    min_eval_score: float | None = Field(default=None, ge=0, le=1)


class MemoryConfig(BaseModel):
    read_workflow_memory: bool = False
    write_workflow_memory: bool = False
    memory_key: str | None = None


CONTEXT_SOURCES = ["system", "instructions", "user_input", "upstream", "knowledge", "memory", "artifacts", "history", "tools"]


class ContextSourcePolicy(BaseModel):
    strategy: Literal["keep", "truncate", "summarize", "extract", "drop"] = "truncate"
    max_tokens: int | None = Field(default=None, ge=1)


class ContextConfig(BaseModel):
    include_run_input: bool = True
    include_direct_upstream: bool = True  # only immediate predecessors, never full history
    max_context_tokens: int | None = None  # V2: the context budget
    truncation: Literal["truncate_end", "truncate_middle", "error"] = "truncate_middle"
    # V2 context engineering (all optional; defaults keep V1 behaviour)
    priority: list[str] = Field(default_factory=lambda: ["system", "instructions", "user_input", "upstream", "knowledge",
                                                          "artifacts", "memory", "history"])
    sources: dict[str, ContextSourcePolicy] = Field(default_factory=dict)
    upstream_keys: list[str] | None = None  # None = all direct upstream; otherwise an explicit selection
    retrieval_top_k: int = Field(default=5, ge=0, le=50)
    history_window: int = Field(default=10, ge=0, le=200)
    artifact_mode: Literal["reference", "extract"] = "reference"  # artifacts enter prompts only when explicitly extracted
    artifact_max_tokens: int = Field(default=4000, ge=0)


class RetryPolicy(BaseModel):
    retries: int = Field(default=0, ge=0, le=10)
    backoff: Literal["none", "fixed", "exponential"] = "exponential"
    base_delay_seconds: float = Field(default=1.0, ge=0, le=60)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str = "general"
    library_agent_id: str | None = None  # start from a library agent's current configuration
    agent_id: str | None = None  # library agent the node was created from (attribution in traces)
    role: str = ""
    instructions: str = ""
    prompt: str = ""  # user-message template with {{variables}}
    model: ModelRef = Field(default_factory=ModelRef)
    params: ModelParams = Field(default_factory=ModelParams)
    tools: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: Literal["stop", "continue", "skip", "route_error"] = "stop"
    fallbacks: list[ModelRef] = Field(default_factory=list)
    max_tool_iterations: int = Field(default=8, ge=0, le=50)
    reasoning_summary: bool = False
    routing: RoutingConfig = Field(default_factory=RoutingConfig)  # used when model.provider == "auto"

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, v: list[str]) -> list[str]:
        unknown = [t for t in v if t not in TOOL_NAMES and not MCP_TOOL_RE.match(t)]
        if unknown:
            raise ValueError(f"Unknown tools: {unknown}")
        return v


class Rule(BaseModel):
    left: str
    operator: Literal["==", "!=", ">", ">=", "<", "<=", "contains", "exists", "not_exists"] = "=="
    right: Any = None


class Route(Rule):
    name: str


class ConditionConfig(BaseModel):
    rule: Rule = Field(default_factory=lambda: Rule(left="", operator="exists"))


class RouterConfig(BaseModel):
    routes: list[Route] = Field(default_factory=list)


class MergeConfig(BaseModel):
    strategy: Literal["object", "array", "named"] = "named"
    wait_for: Literal["all_active", "any"] = "all_active"


class LoopConfig(BaseModel):
    collection: str = ""  # expression resolving to a list (loop) — empty for retry-style loops
    max_iterations: int = Field(default=10, ge=1)
    stop_condition: Rule | None = None


class TransformConfig(BaseModel):
    mode: Literal["template", "select", "json_parse", "to_text", "mapping", "csv_to_table"] = "template"
    template: str = ""
    path: str = ""
    mapping: dict[str, str] = Field(default_factory=dict)


class ApprovalConfig(BaseModel):
    title: str = "Approval required"
    instructions: str = ""
    content: str = ""  # template for what the reviewer sees; defaults to upstream output
    allow_edit: bool = True
    timeout_hours: int | None = None
    max_wait_seconds: int | None = Field(default=None, ge=1)  # V2 durable wait timeout
    timeout_action: Literal["edge", "fail", "continue"] = "edge"


class InputConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    field: str = "value"  # key in run input
    label: str = ""
    required: bool = True
    default: Any = None
    json_schema: dict[str, Any] | None = None
    as_artifact: bool = False  # V2: file input passes an ArtifactRef instead of extracted text


class ToolNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    arguments: dict[str, Any] = Field(default_factory=dict)  # values may contain {{templates}}
    credential_id: str | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: Literal["stop", "continue", "skip", "route_error"] = "stop"
    timeout_seconds: int = Field(default=60, ge=1, le=900)


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    template: str = ""  # empty = pass upstream output through
    format: Literal["text", "json", "markdown", "file"] = "text"
    filename: str | None = None
    json_schema: dict[str, Any] | None = None


class TriggerNodeConfig(BaseModel):
    """Entry node for triggered runs. Outputs the trigger payload (run input)."""
    model_config = ConfigDict(extra="allow")
    payload_schema: dict[str, Any] | None = None
    description: str = ""


class WaitConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    duration_seconds: int | None = Field(default=None, ge=1)  # wait_timer
    until: str = ""  # wait_timer: ISO timestamp or {{expression}}
    event_name: str = ""  # wait_event
    correlation: str = ""  # wait_event: expression resolved at wait time, matched against the incoming event
    max_wait_seconds: int | None = Field(default=None, ge=1)
    timeout_action: Literal["edge", "fail", "continue"] = "edge"


class SubworkflowConfig(BaseModel):
    workflow_id: str = ""
    version: int | None = None  # pinned, immutable published version
    input_mapping: dict[str, str] = Field(default_factory=dict)  # child input field -> expression
    on_failure: Literal["stop", "continue", "skip", "route_error"] = "stop"


class TeamBudget(BaseModel):
    max_messages: int = Field(default=40, ge=1, le=1000)
    max_rounds: int = Field(default=8, ge=1, le=100)
    max_agent_calls: int = Field(default=20, ge=1, le=500)
    max_tokens: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    max_duration_seconds: int = Field(default=600, ge=1, le=86400)


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "agent": AgentConfig,
    "condition": ConditionConfig,
    "router": RouterConfig,
    "merge": MergeConfig,
    "loop": LoopConfig,
    "retry": LoopConfig,
    "transform": TransformConfig,
    "human_approval": ApprovalConfig,
    **{t: InputConfig for t in INPUT_TYPES},
    **{t: ToolNodeConfig for t in TOOL_TYPES},
    **{t: OutputConfig for t in OUTPUT_TYPES},
    **{t: TriggerNodeConfig for t in TRIGGER_TYPES},
    **{t: WaitConfig for t in WAIT_TYPES},
    "subworkflow": SubworkflowConfig,
}


# ---------------------------------------------------------------------------------------------- harness
class PortSpec(BaseModel):
    name: str = Field(default="in", pattern=r"^[a-z][a-z0-9_]{0,47}$")
    type: str = "Any"  # Text | Number | JSON<Name> | Artifact<csv> | Table | ... | custom type name
    required: bool = True
    description: str = ""


class Contract(BaseModel):
    """Formal node contract. Enforced at compile time (types/capabilities) and at runtime (schemas, cost, time)."""
    inputs: list[PortSpec] = Field(default_factory=list)
    output: PortSpec = Field(default_factory=lambda: PortSpec(name="out"))
    capabilities: list[Literal["text", "vision", "tool_calling", "structured_output", "reasoning", "large_context", "coding"]] = Field(default_factory=list)
    min_context_tokens: int | None = Field(default=None, ge=1)
    allowed_tools: list[str] | None = None  # None = whatever the agent config grants
    side_effects: Literal["none", "read", "write", "external_write"] = "none"
    artifact_types: list[str] = Field(default_factory=list)
    max_cost: float | None = Field(default=None, ge=0)
    timeout_seconds: int | None = Field(default=None, ge=1)


class CachePolicy(BaseModel):
    mode: Literal["disabled", "exact", "semantic"] = "disabled"
    ttl_seconds: int = Field(default=86400, ge=1, le=90 * 86400)
    similarity_threshold: float = Field(default=0.95, ge=0.5, le=1.0)


class SlaPolicy(BaseModel):
    max_latency_ms: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    on_breach: Literal["fallback", "degrade", "fail", "alert"] = "fail"


RECOVERY_ERRORS = ["rate_limit", "timeout", "unavailable", "model_unavailable", "structured_output", "context_limit",
                   "tool_error", "contract_violation", "auth", "any"]
RECOVERY_ACTIONS = ["retry", "fallback", "switch_provider", "repair", "reduce_context", "route_error", "human",
                    "degrade", "fail"]


class RecoveryRule(BaseModel):
    when: list[str] = Field(default_factory=lambda: ["any"])
    attempts_gte: int | None = Field(default=None, ge=1)  # rule applies once this many attempts failed
    actions: list[str] = Field(default_factory=lambda: ["retry"])

    @field_validator("when")
    @classmethod
    def _errs(cls, v):
        bad = [x for x in v if x not in RECOVERY_ERRORS]
        if bad:
            raise ValueError(f"Unknown error kinds {bad}")
        return v

    @field_validator("actions")
    @classmethod
    def _acts(cls, v):
        bad = [x for x in v if x not in RECOVERY_ACTIONS]
        if bad:
            raise ValueError(f"Unknown recovery actions {bad}")
        return v


class Compensation(BaseModel):
    """Compensating action for a side effect (e.g. DELETE what a POST created). Never run implicitly."""
    tool: Literal["http_request"] = "http_request"
    arguments: dict[str, Any] = Field(default_factory=dict)  # may reference {{this.output...}}
    description: str = ""


class Harness(BaseModel):
    cache: CachePolicy = Field(default_factory=CachePolicy)
    sla: SlaPolicy = Field(default_factory=SlaPolicy)
    recovery: list[RecoveryRule] = Field(default_factory=list)
    checkpoint: bool = False  # explicit user checkpoint after this node
    compensation: Compensation | None = None
    resource_class: Literal["standard", "cpu_heavy", "memory_heavy", "sandbox", "long_running"] = "standard"


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=64)
    key: str  # human-readable variable name, e.g. "research" → {{research.output}}
    type: str
    name: str = ""
    position: Position = Field(default_factory=Position)
    parent_id: str | None = None  # visual grouping only
    config: dict[str, Any] = Field(default_factory=dict)
    # V2 — kept separate from prompts/config on purpose
    contract: Contract | None = None
    harness: Harness = Field(default_factory=Harness)

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in NODE_TYPES:
            raise ValueError(f"Unknown node type '{v}'")
        return v

    @field_validator("key")
    @classmethod
    def _key_format(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError("Node key must be lowercase letters, digits or underscores and start with a letter")
        if v in RESERVED_KEYS:
            raise ValueError(f"'{v}' is a reserved variable name")
        return v

    def typed_config(self) -> BaseModel | None:
        m = CONFIG_MODELS.get(self.type)
        return m.model_validate(self.config) if m else None

    @property
    def executable(self) -> bool:
        return self.type not in ANNOTATION_TYPES


class Edge(BaseModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None  # "true"/"false", route name, "approved"/"rejected", "body"/"done", "error", "timeout"
    target_handle: str | None = None  # V2: input port name when the target declares several ports


class WorkflowSettings(BaseModel):
    max_runtime_seconds: int = Field(default=600, ge=1)
    max_llm_calls: int = Field(default=50, ge=1)
    max_tool_calls: int = Field(default=100, ge=0)
    max_loop_iterations: int = Field(default=10, ge=1)
    max_retries_per_node: int = Field(default=3, ge=0)
    max_parallel_nodes: int = Field(default=10, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    max_total_tokens: int | None = Field(default=None, ge=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    workflow_memory_enabled: bool = False
    compensation_enabled: bool = False  # run registered compensations automatically when the run fails
    mode: Literal["graph", "goal"] = "graph"
    goal: "GoalConfig | None" = None


class GoalConfig(BaseModel):
    """Goal Mode: the harness planner composes allowed agents/tools into a graph, within hard bounds."""
    goal: str = ""
    agents: list[str] = Field(default_factory=list)  # agent template ids or library agent ids ("lib:<uuid>")
    tools: list[str] = Field(default_factory=list)
    planner_model: ModelRef = Field(default_factory=ModelRef)
    agent_model: ModelRef = Field(default_factory=ModelRef)
    constraints: str = ""
    max_agent_calls: int = Field(default=15, ge=1, le=100)
    max_planning_depth: int = Field(default=8, ge=1, le=30)  # max nodes per plan
    max_replans: int = Field(default=1, ge=0, le=5)
    output_schema: dict[str, Any] | None = None  # required output contract


WorkflowSettings.model_rebuild()


class WorkflowGraph(BaseModel):
    schema_version: str = SCHEMA_VERSION
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported schema version {v}")
        return SCHEMA_VERSION  # 1.0 upgrades losslessly: all V2 fields are optional

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate node ids")
        keys = [n.key for n in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate node keys")
        eids = [e.id for e in self.edges]
        if len(eids) != len(set(eids)):
            raise ValueError("Duplicate edge ids")
        return self

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)


class WorkflowDocument(BaseModel):
    """The exportable/importable document (workflow.json)."""
    schema_version: str = SCHEMA_VERSION
    name: str
    description: str = ""
    graph: WorkflowGraph

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported schema version {v}")
        return SCHEMA_VERSION
