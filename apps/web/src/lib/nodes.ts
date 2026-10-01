import type { NodeType, WFNode } from "./types";

export type Category = "trigger" | "input" | "agent" | "logic" | "wait" | "tool" | "output" | "annotation";

export interface NodeSpec {
  type: NodeType;
  category: Category;
  label: string;
  description: string;
  icon: string; // lucide icon name
  defaultKey: string;
  defaults: () => Record<string, any>;
}

const retry = () => ({ retries: 0, backoff: "exponential", base_delay_seconds: 1 });

export const NODE_SPECS: NodeSpec[] = [
  { type: "trigger_webhook", category: "trigger", label: "Webhook trigger", description: "Starts from a signed HTTP request (configure under Triggers)", icon: "Webhook", defaultKey: "webhook", defaults: () => ({ payload_schema: null, description: "" }) },
  { type: "trigger_schedule", category: "trigger", label: "Schedule trigger", description: "Starts on a cron schedule (configure under Triggers)", icon: "CalendarClock", defaultKey: "schedule", defaults: () => ({ description: "" }) },
  { type: "trigger_event", category: "trigger", label: "Event trigger", description: "Starts when an external event is published", icon: "Radio", defaultKey: "event", defaults: () => ({ description: "" }) },
  { type: "trigger_file", category: "trigger", label: "File trigger", description: "Starts when a file is uploaded to the project", icon: "FileInput", defaultKey: "file_upload", defaults: () => ({ description: "" }) },
  { type: "input_text", category: "input", label: "Text input", description: "A text value supplied when the run starts", icon: "Type", defaultKey: "text", defaults: () => ({ field: "text", label: "", required: true }) },
  { type: "input_json", category: "input", label: "JSON input", description: "Structured input, optionally validated by a schema", icon: "Braces", defaultKey: "data", defaults: () => ({ field: "data", required: true, json_schema: null }) },
  { type: "input_file", category: "input", label: "File input", description: "An uploaded project document (PDF, DOCX, TXT, MD, CSV, JSON)", icon: "FileUp", defaultKey: "file", defaults: () => ({ field: "file", required: true }) },
  { type: "input_url", category: "input", label: "URL input", description: "An http(s) URL", icon: "Link", defaultKey: "url", defaults: () => ({ field: "url", required: true }) },
  { type: "input_chat", category: "input", label: "Chat input", description: "A list of chat messages", icon: "MessagesSquare", defaultKey: "chat", defaults: () => ({ field: "messages", required: true }) },

  { type: "agent", category: "agent", label: "Agent", description: "An LLM-powered agent with a role, model and tools", icon: "Bot", defaultKey: "agent",
    defaults: () => ({ template: "general", role: "", instructions: "", prompt: "", model: { provider: "", model: "" }, params: { temperature: 0.3 },
      tools: [], knowledge_base_ids: [], memory: { read_workflow_memory: false, write_workflow_memory: false }, context: { include_run_input: true, include_direct_upstream: true, truncation: "truncate_middle" },
      output_schema: null, timeout_seconds: 120, retry: { retries: 2, backoff: "exponential", base_delay_seconds: 1 }, on_failure: "stop", fallbacks: [], max_tool_iterations: 8, reasoning_summary: false }) },

  { type: "condition", category: "logic", label: "Condition", description: "Branch true/false on a rule", icon: "GitBranch", defaultKey: "check", defaults: () => ({ rule: { left: "", operator: ">", right: "" } }) },
  { type: "router", category: "logic", label: "Router", description: "Send work down the first matching route", icon: "Split", defaultKey: "route", defaults: () => ({ routes: [{ name: "route_a", left: "", operator: "contains", right: "" }] }) },
  { type: "parallel", category: "logic", label: "Parallel", description: "Fan out: connected branches run at the same time", icon: "Columns3", defaultKey: "fan_out", defaults: () => ({}) },
  { type: "merge", category: "logic", label: "Merge", description: "Wait for active branches and combine their outputs", icon: "Merge", defaultKey: "merge", defaults: () => ({ strategy: "named", wait_for: "all_active" }) },
  { type: "loop", category: "logic", label: "Loop", description: "Run the connected body for each item, bounded", icon: "Repeat", defaultKey: "loop", defaults: () => ({ collection: "", max_iterations: 5, stop_condition: null }) },
  { type: "retry", category: "logic", label: "Retry until", description: "Repeat the body until a success condition holds", icon: "RotateCcw", defaultKey: "retry_until", defaults: () => ({ max_iterations: 3, stop_condition: { left: "", operator: "exists", right: null } }) },
  { type: "transform", category: "logic", label: "Transform", description: "Reshape data with a template, path or mapping", icon: "Shuffle", defaultKey: "transform", defaults: () => ({ mode: "template", template: "", path: "", mapping: {} }) },
  { type: "human_approval", category: "logic", label: "Human approval", description: "Pause the run until someone approves or rejects", icon: "UserCheck", defaultKey: "approval", defaults: () => ({ title: "Approval required", instructions: "", content: "", allow_edit: true }) },

  { type: "wait_timer", category: "wait", label: "Wait (timer)", description: "Pause durably for a duration or until a time", icon: "Timer", defaultKey: "wait", defaults: () => ({ duration_seconds: 3600, until: "", max_wait_seconds: null, timeout_action: "edge" }) },
  { type: "wait_webhook", category: "wait", label: "Wait for callback", description: "Pause until an external system calls back ({{run.callbacks.key}})", icon: "PhoneIncoming", defaultKey: "callback", defaults: () => ({ max_wait_seconds: 86400, timeout_action: "edge" }) },
  { type: "wait_event", category: "wait", label: "Wait for event", description: "Pause until a matching event is published", icon: "BellRing", defaultKey: "await_event", defaults: () => ({ event_name: "", correlation: "", max_wait_seconds: 86400, timeout_action: "edge" }) },
  { type: "subworkflow", category: "logic", label: "Sub-workflow", description: "Run a published version of another workflow as one step", icon: "Boxes", defaultKey: "subworkflow", defaults: () => ({ workflow_id: "", version: null, input_mapping: {}, on_failure: "stop" }) },
  { type: "tool_web_search", category: "tool", label: "Web search", description: "Search the web", icon: "Globe", defaultKey: "search", defaults: () => ({ arguments: { query: "", max_results: 5 }, retry: retry(), on_failure: "stop", timeout_seconds: 60 }) },
  { type: "tool_http", category: "tool", label: "HTTP request", description: "Call an external API (private networks blocked)", icon: "Send", defaultKey: "http", defaults: () => ({ arguments: { method: "GET", url: "", headers: {}, body: null }, retry: retry(), on_failure: "stop", timeout_seconds: 60 }) },
  { type: "tool_python", category: "tool", label: "Python", description: "Run code in the isolated sandbox", icon: "Terminal", defaultKey: "python", defaults: () => ({ arguments: { code: "print(INPUTS)", inputs: {} }, retry: retry(), on_failure: "stop", timeout_seconds: 60 }) },
  { type: "tool_calculator", category: "tool", label: "Calculator", description: "Evaluate an arithmetic expression safely", icon: "Calculator", defaultKey: "calc", defaults: () => ({ arguments: { expression: "" }, retry: retry(), on_failure: "stop", timeout_seconds: 10 }) },
  { type: "tool_file_reader", category: "tool", label: "File reader", description: "Read text from an uploaded document", icon: "FileText", defaultKey: "reader", defaults: () => ({ arguments: { document_id: "" }, retry: retry(), on_failure: "stop", timeout_seconds: 60 }) },
  { type: "tool_json", category: "tool", label: "JSON processor", description: "Parse, select or validate JSON", icon: "Brackets", defaultKey: "json_tool", defaults: () => ({ arguments: { operation: "parse", data: "" }, retry: retry(), on_failure: "stop", timeout_seconds: 10 }) },
  { type: "tool_vector_search", category: "tool", label: "Knowledge search", description: "Retrieve passages from a knowledge base", icon: "Library", defaultKey: "kb_search", defaults: () => ({ arguments: { query: "", top_k: 5 }, knowledge_base_ids: [], retry: retry(), on_failure: "stop", timeout_seconds: 30 }) },

  { type: "output_text", category: "output", label: "Text output", description: "Final text result", icon: "AlignLeft", defaultKey: "output", defaults: () => ({ template: "", format: "text" }) },
  { type: "output_json", category: "output", label: "JSON output", description: "Final structured result", icon: "FileJson", defaultKey: "result", defaults: () => ({ template: "", format: "json", json_schema: null }) },
  { type: "output_file", category: "output", label: "File output", description: "Produce a downloadable file", icon: "FileDown", defaultKey: "file_out", defaults: () => ({ template: "", format: "file", filename: "result.md" }) },
  { type: "output_report", category: "output", label: "Report", description: "Markdown report", icon: "ScrollText", defaultKey: "report", defaults: () => ({ template: "", format: "markdown" }) },
  { type: "output_api", category: "output", label: "API response", description: "Structured response for API callers", icon: "Webhook", defaultKey: "response", defaults: () => ({ template: "", format: "json" }) },

  { type: "note", category: "annotation", label: "Note", description: "A comment on the canvas (not executed)", icon: "StickyNote", defaultKey: "note", defaults: () => ({ text: "" }) },
  { type: "group", category: "annotation", label: "Group", description: "Visually group related nodes (not executed)", icon: "SquareDashed", defaultKey: "group", defaults: () => ({ width: 520, height: 320 }) },
];

export const SPEC: Record<string, NodeSpec> = Object.fromEntries(NODE_SPECS.map((s) => [s.type, s]));

export const CATEGORY_LABEL: Record<Category, string> = {
  trigger: "Triggers", input: "Inputs", agent: "Agents", logic: "Logic", wait: "Waits", tool: "Tools", output: "Outputs", annotation: "Canvas",
};

export const CATEGORY_TINT: Record<Category, string> = {
  trigger: "#B4531A", input: "#127C74", agent: "#4A5BD4", logic: "#8A5CC9", wait: "#C98A1B", tool: "#2E7DA8", output: "#3B7A3F", annotation: "#8C969B",
};

/** Source handles a node exposes (null = the default "out" handle). */
export function sourceHandles(n: WFNode): { id: string | null; label?: string; tone?: "ok" | "bad" | "neutral" }[] {
  switch (n.type) {
    case "condition": return [{ id: "true", label: "true", tone: "ok" }, { id: "false", label: "false", tone: "bad" }];
    case "router": return [...(n.config.routes || []).map((r: any) => ({ id: r.name, label: r.name, tone: "neutral" as const })), { id: "default", label: "default", tone: "neutral" as const }];
    case "human_approval": {
      const hs: { id: string | null; label?: string; tone?: "ok" | "bad" | "neutral" }[] = [{ id: "approved", label: "approved", tone: "ok" }, { id: "rejected", label: "rejected", tone: "bad" }];
      if (n.config?.max_wait_seconds && (n.config?.timeout_action || "edge") === "edge") hs.push({ id: "timeout", label: "timeout", tone: "neutral" });
      return hs;
    }
    case "wait_timer": case "wait_webhook": case "wait_event": {
      const hs: { id: string | null; label?: string; tone?: "ok" | "bad" | "neutral" }[] = [{ id: null }];
      if (n.config?.max_wait_seconds && (n.config?.timeout_action || "edge") === "edge") hs.push({ id: "timeout", label: "timeout", tone: "neutral" });
      return hs;
    }
    case "loop": case "retry": return [{ id: "body", label: "each", tone: "neutral" }, { id: "done", label: "done", tone: "ok" }];
    case "output_text": case "output_json": case "output_file": case "output_report": case "output_api": case "note": case "group": return [];
    default: {
      const hs: { id: string | null; label?: string; tone?: "ok" | "bad" | "neutral" }[] = [{ id: null }];
      if (n.config?.on_failure === "route_error") hs.push({ id: "error", label: "error", tone: "bad" });
      return hs;
    }
  }
}

export function hasTarget(n: WFNode) {
  return !n.type.startsWith("input_") && !n.type.startsWith("trigger_") && n.type !== "note" && n.type !== "group";
}

export function isEntry(t: string) {
  return t.startsWith("input_") || t.startsWith("trigger_");
}

export function isExecutable(t: string) {
  return t !== "note" && t !== "group";
}
