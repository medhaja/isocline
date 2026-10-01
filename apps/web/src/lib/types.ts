/* Mirrors the backend workflow schema v1.0 (apps/api/isocline/schemas/workflow.py).
   The canonical JSON Schema lives in packages/workflow-schema. */

export type NodeType =
  | "input_text" | "input_json" | "input_file" | "input_url" | "input_chat"
  | "agent"
  | "condition" | "router" | "parallel" | "merge" | "loop" | "retry" | "transform" | "human_approval"
  | "tool_web_search" | "tool_http" | "tool_python" | "tool_calculator" | "tool_file_reader" | "tool_json" | "tool_vector_search"
  | "output_text" | "output_json" | "output_file" | "output_report" | "output_api"
  | "trigger_webhook" | "trigger_schedule" | "trigger_event" | "trigger_file"
  | "wait_timer" | "wait_webhook" | "wait_event" | "subworkflow"
  | "group" | "note";

export interface PortSpec { name: string; type: string; required?: boolean; description?: string }
export interface Contract {
  inputs: PortSpec[]; output: PortSpec; capabilities: string[]; min_context_tokens?: number | null; allowed_tools?: string[] | null;
  side_effects: "none" | "read" | "write" | "external_write"; artifact_types?: string[]; max_cost?: number | null; timeout_seconds?: number | null;
}
export interface Harness {
  cache?: { mode: "disabled" | "exact" | "semantic"; ttl_seconds?: number; similarity_threshold?: number };
  sla?: { max_latency_ms?: number | null; max_cost?: number | null; max_tokens?: number | null; max_attempts?: number | null; on_breach?: string };
  recovery?: { when: string[]; attempts_gte?: number | null; actions: string[] }[];
  checkpoint?: boolean;
  compensation?: { tool: "http_request"; arguments: Record<string, any>; description?: string } | null;
  resource_class?: string;
}

export interface WFNode {
  id: string;
  key: string;
  type: NodeType;
  name: string;
  position: { x: number; y: number };
  parent_id?: string | null;
  config: Record<string, any>;
  contract?: Contract | null;
  harness?: Harness;
}

export interface WFEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
}

export interface WFSettings {
  max_runtime_seconds?: number;
  max_llm_calls?: number;
  max_tool_calls?: number;
  max_loop_iterations?: number;
  max_retries_per_node?: number;
  max_parallel_nodes?: number;
  max_cost?: number | null;
  max_total_tokens?: number | null;
  variables?: Record<string, any>;
  workflow_memory_enabled?: boolean;
  compensation_enabled?: boolean;
  mode?: "graph" | "goal";
  goal?: GoalConfig | null;
}

export interface GoalConfig {
  goal: string; agents: string[]; tools: string[]; planner_model: ModelRef; agent_model: ModelRef; constraints?: string;
  max_agent_calls: number; max_planning_depth: number; max_replans: number; output_schema?: Record<string, any> | null;
}

export interface WorkflowGraph {
  schema_version: string; // "2.0" (1.0 documents are upgraded on load)
  nodes: WFNode[];
  edges: WFEdge[];
  settings: WFSettings;
}

export interface ModelRef { provider: string; model: string; credential_id?: string | null }

export interface Workflow {
  id: string; project_id: string; name: string; description: string; status: "draft" | "published" | "archived";
  revision: number; latest_version: number; created_at: string; updated_at: string; node_count: number;
  graph?: WorkflowGraph; workspace_id?: string; project_name?: string; last_run_at?: string | null;
}

export type RunStatus = "queued" | "running" | "waiting" | "resuming" | "completed" | "failed" | "cancelled";
export type NodeStatus = "queued" | "running" | "completed" | "failed" | "skipped" | "waiting" | "cancelled";

export interface Run {
  id: string; workflow_id: string; workflow_name?: string; project_id: string; status: RunStatus; trigger: string;
  input: any; output: any; error: any; parent_run_id: string | null; replay_from_node_id: string | null;
  created_at: string; started_at: string | null; finished_at: string | null; duration_ms?: number;
  llm_calls: number; tool_calls: number; input_tokens: number; output_tokens: number; cost_usd: number; cost_is_estimate: boolean;
  limits: Record<string, any>; graph_snapshot?: WorkflowGraph; approvals?: Approval[]; replays?: { id: string; status: string; created_at: string }[];
  workflow_version_id?: string | null; recovery_attempts?: number;
}

export interface ToolRun { id: string; tool: string; input: any; output: any; success: boolean; error: string | null; duration_ms: number | null; started_at: string }

export interface NodeRun {
  id: string; node_id: string; node_key: string; node_type: string; scope: string; status: NodeStatus;
  input: any; config: any; output: any; handle: string | null; error: any; attempts: any[];
  provider: string | null; model: string | null; fallback_used: boolean; llm_calls: number;
  input_tokens: number; output_tokens: number; cached_tokens: number; cost_usd: number;
  reasoning_summary: string | null; started_at: string | null; finished_at: string | null; latency_ms: number | null;
  tool_runs: ToolRun[];
}

export interface RunEvent { seq: number; type: string; data: any; ts: string | null }

export interface Approval {
  id: string; run_id: string; node_id: string; scope: string; status: string; title: string; instructions: string;
  content: any; allow_edit: boolean; edited_content: any; comment: string | null; decided_at: string | null; created_at: string;
  workflow_name?: string; workflow_id?: string;
}

export interface Issue { severity: "error" | "warning"; code: string; message: string; node_id?: string; edge_id?: string }

export interface Project { id: string; workspace_id: string; name: string; description: string; created_at: string; workflow_count?: number; run_count?: number }
export interface Workspace { id: string; name: string; role: string; created_at: string }
export interface User { id: string; email: string; name: string; email_verified: boolean; is_admin: boolean }

export interface ProviderInfo { id: string; name: string; requires_key: boolean; default_base_url: string | null; configured: boolean; has_credential: boolean; is_test: boolean; all_params: string[] }
export interface ModelInfo { id: string; name: string; context_window: number | null; supported_params: string[]; pricing: { input_per_mtok: number; output_per_mtok: number } | null; source: string }

export interface PlanCheck { category: string; status: "pass" | "warn" | "fail" | "info"; message: string; node_id?: string }
export interface ExecutionPlan {
  status: "READY" | "BLOCKED";
  counts: { nodes: number; agents: number; logic: number; tools: number; parallel_branches: number; human_approvals: number; durable_waits: number; subworkflows: number };
  totals: { llm_calls: [number, number]; tokens: [number, number]; cost_usd: [number, number]; active_seconds: [number, number] } | null;
  nodes: any[]; checks: PlanCheck[]; warnings: string[]; note?: string;
}
export interface Credential { id: string; provider: string; name: string; hint: string; base_url: string | null; created_at: string; has_value: boolean }
