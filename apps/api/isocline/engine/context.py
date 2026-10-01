"""Context engineering: explicit, budgeted assembly of what enters a model call.

Sections are categorised (system, instructions, request, user_input, upstream, artifacts, knowledge, memory, history,
tools). When the estimate exceeds the context budget, sections are reduced in reverse priority order using the
per-source strategy (truncate | extract | summarize | drop). Every reduction is recorded in the node trace.
Artifacts never enter prompts as raw bytes: they appear as references unless extraction is explicitly enabled.

Agents without any V2 context options use the unchanged V1 assembly (backward compatibility)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from isocline.providers.base import Message
from isocline.schemas.workflow import AgentConfig

from .expressions import Scope, render, to_text
from .pricing import estimate_tokens
from .types import is_artifact_ref

DEFAULT_PRIORITY = ["system", "instructions", "user_input", "upstream", "knowledge", "artifacts", "memory", "history"]
NEVER_REDUCED = {"system", "request", "tools"}


@dataclass
class Section:
    category: str
    label: str
    text: str
    wrap: str = ""  # tag name used when rendering
    attrs: str = ""
    trace: dict = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text) if self.text else 0

    def render(self) -> str:
        if not self.text:
            return ""
        if not self.wrap:
            return self.text
        return f"<{self.wrap}{(' ' + self.attrs) if self.attrs else ''}>\n{self.text}\n</{self.wrap}>"


def uses_v2_context(cfg: AgentConfig) -> bool:
    c = cfg.context
    return bool(c.sources) or c.upstream_keys is not None or c.artifact_mode == "extract" or list(c.priority) != DEFAULT_PRIORITY


def _render_value(val: Any) -> str:
    """Upstream values: artifact references are described, never inlined."""
    def describe(v):
        if is_artifact_ref(v):
            return {"artifact": v.get("name"), "type": v.get("type"), "size_bytes": v.get("size"), "artifact_id": v.get("artifact_id")}
        if isinstance(v, dict):
            return {k: describe(x) for k, x in v.items()}
        if isinstance(v, list):
            return [describe(x) for x in v]
        return v
    return to_text(describe(val))


def find_artifact_refs(val: Any) -> list[dict]:
    out: list[dict] = []
    if is_artifact_ref(val):
        out.append(val)
    elif isinstance(val, dict):
        for v in val.values():
            out += find_artifact_refs(v)
    elif isinstance(val, list):
        for v in val:
            out += find_artifact_refs(v)
    return out


def _truncate_text(text: str, max_tokens: int, mode: str = "middle") -> str:
    max_chars = max(0, max_tokens * 4)
    if len(text) <= max_chars:
        return text
    marker = "\n…[trimmed by context policy]…\n"
    if mode == "end":
        return text[:max_chars] + marker
    half = max_chars // 2
    return text[:half] + marker + text[-half:]


_WORD = re.compile(r"[a-z0-9]{3,}")


def extract_relevant(text: str, query: str, max_tokens: int) -> str:
    """Keeps the paragraphs sharing most terms with the request, in original order."""
    q = set(_WORD.findall(query.lower()))
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return _truncate_text(text, max_tokens)
    scored = sorted(range(len(paras)), key=lambda i: -len(q & set(_WORD.findall(paras[i].lower()))))
    keep, used = set(), 0
    for i in scored:
        t = estimate_tokens(paras[i])
        if used + t > max_tokens:
            continue
        keep.add(i)
        used += t
    return "\n\n".join(paras[i] for i in sorted(keep)) or _truncate_text(text, max_tokens)


async def assemble(cfg: AgentConfig, node, scope: Scope, upstream: dict[str, Any], ctx, *, preview: bool = False,
                   budget_override: int | None = None, tool_tokens: int = 0) -> tuple[list[Message], dict]:
    """V2 assembly. Returns messages and the inspector record including `context_trace`."""
    from .agent_runtime import REASONING_MARK, TRUST_POLICY
    c = cfg.context
    sections: list[Section] = []
    sys_lines = [f"You are the '{node.name or node.key}' agent in a multi-agent workflow."]
    if cfg.role:
        sys_lines.append(f"Role: {cfg.role}")
    sys_lines.append(TRUST_POLICY)
    if cfg.output_schema:
        sys_lines.append("Return only data matching the required output structure.")
    elif cfg.reasoning_summary:
        sys_lines.append(f"After your answer, add a final line starting with '{REASONING_MARK}' giving a 1-3 sentence summary of how you reached it.")
    sections.append(Section("system", "System", "\n\n".join(sys_lines)))
    if cfg.instructions:
        sections.append(Section("instructions", "Agent instructions", f"Instructions:\n{render(cfg.instructions, scope)}"))
    prompt = (render(cfg.prompt, scope).strip() if cfg.prompt else "") or "Complete your task using the context provided."
    record: dict[str, Any] = {"prompt": prompt, "context_mode": "v2"}

    run_input = scope.root.get("input")
    if c.include_run_input and run_input:
        history, rest = None, run_input
        if isinstance(run_input, dict):
            for k, v in run_input.items():
                if isinstance(v, list) and v and all(isinstance(m, dict) and "content" in m for m in v):
                    history = v[-c.history_window:] if c.history_window else []
                    rest = {kk: vv for kk, vv in run_input.items() if kk != k}
                    break
        if rest:
            sections.append(Section("user_input", "User input", _render_value(rest), "external_content", 'source="workflow_input"'))
        if history:
            sections.append(Section("history", f"Conversation history ({len(history)} messages)",
                                    "\n".join(f"{m.get('role', 'user')}: {m.get('content')}" for m in history), "external_content", 'source="history"'))
        record["workflow_input"] = run_input
    refs: list[dict] = []
    if c.include_direct_upstream and upstream:
        chosen = {k: v for k, v in upstream.items() if c.upstream_keys is None or k in c.upstream_keys}
        for key, val in chosen.items():
            sections.append(Section("upstream", f"Output of {key}", _render_value(val), "upstream_output", f'node="{key}"'))
            refs += find_artifact_refs(val)
        record["upstream"] = chosen
    if refs and c.artifact_mode == "extract" and not preview:
        for r in refs[:5]:
            text = await ctx.artifact_text(r["artifact_id"], c.artifact_max_tokens * 4)
            sections.append(Section("artifacts", f"Artifact {r.get('name')}", text or "", "external_content", f'source="artifact:{r.get("name")}"'))
    elif refs:
        record["artifact_refs"] = refs
    if cfg.memory.read_workflow_memory and ctx.limits.get("workflow_memory_enabled"):
        mem = await ctx.memory()
        if mem:
            sections.append(Section("memory", "Workflow memory", to_text(mem), "external_content", 'source="workflow_memory"'))
            record["workflow_memory"] = mem
    if cfg.knowledge_base_ids and "vector_search" not in cfg.tools and c.retrieval_top_k:
        hits = await ctx.retrieve(cfg.knowledge_base_ids, (prompt or to_text(run_input))[:2000])
        hits = (hits or [])[: c.retrieval_top_k]
        if hits:
            sections.append(Section("knowledge", f"Retrieved knowledge ({len(hits)} passages)",
                                    "\n\n".join(f"[{i + 1}] ({h['source']} #{h['chunk']}) {h['content']}" for i, h in enumerate(hits)), "knowledge"))
            record["retrieved_knowledge"] = hits

    # ------------------------------------------------------------------ budget & reduction
    window = (ctx.pricing_cache.get((cfg.model.provider, cfg.model.model)) or {}).get("context_window")
    budget = budget_override or c.max_context_tokens
    if window:
        auto = max(1000, window - (cfg.params.max_tokens or 4096) - 1000)
        budget = min(budget, auto) if budget else auto
    request_tokens = estimate_tokens(prompt) + 10
    for s in sections:
        s.trace = {"category": s.category, "label": s.label, "tokens": s.tokens, "action": "kept"}
    # per-source caps first
    for s in sections:
        pol = c.sources.get(s.category)
        if pol and pol.max_tokens and s.tokens > pol.max_tokens and s.category not in NEVER_REDUCED:
            await _reduce(s, pol.strategy, pol.max_tokens, prompt, ctx, preview)
    total = sum(s.tokens for s in sections) + request_tokens + tool_tokens
    if budget and total > budget:
        prio = [p for p in c.priority if p in {s.category for s in sections}]
        order = [cat for cat in reversed(prio)] + [s.category for s in sections if s.category not in prio and s.category not in NEVER_REDUCED]
        for cat in order:
            if total <= budget:
                break
            if cat in NEVER_REDUCED:
                continue
            for s in [x for x in sections if x.category == cat][::-1]:
                if total <= budget:
                    break
                pol = c.sources.get(cat)
                strategy = pol.strategy if pol else ("truncate" if c.truncation != "error" else "error")
                if strategy == "keep":
                    continue
                if strategy == "error":
                    from .agent_runtime import NodeFailure
                    raise NodeFailure(f"Context is ~{total:,} tokens, above the {budget:,} token budget", kind="context_limit")
                over = total - budget
                # Only an explicit "drop" removes a source entirely; other strategies keep a floor so a
                # configured extract/summarize/truncate never silently turns into a drop.
                floor = 0 if strategy == "drop" else min(s.tokens, max(100, budget // 10))
                target = max(floor, s.tokens - over)
                if target >= s.tokens:
                    continue
                before = s.tokens
                await _reduce(s, strategy, target, prompt, ctx, preview)
                total -= before - s.tokens
    if budget and total > budget:
        if c.truncation == "error":
            from .agent_runtime import NodeFailure
            raise NodeFailure(f"Context is ~{total:,} tokens after reduction, above the {budget:,} token budget", kind="context_limit")
        record["context_over_budget"] = (f"~{total:,} tokens remain after reducing every reducible source; the system prompt and "
                                         f"current request ({request_tokens:,} tokens) are never reduced")

    system = "\n\n".join(x.render() for x in sections if x.category == "system")
    ctx_parts = [x.render() for x in sections if x.category not in ("system",) and x.text]
    user = f"<user_request>\n{prompt}\n</user_request>"
    if ctx_parts:
        user = "Context:\n" + "\n\n".join(ctx_parts) + "\n\n" + user
    trace = [s.trace | {"tokens_after": s.tokens} for s in sections]
    trace.append({"category": "request", "label": "Current request", "tokens": request_tokens, "tokens_after": request_tokens, "action": "kept"})
    if tool_tokens:
        trace.append({"category": "tools", "label": "Tool definitions", "tokens": tool_tokens, "tokens_after": tool_tokens, "action": "kept"})
    record["context_trace"] = trace
    record["context_total_tokens"] = sum(t["tokens_after"] for t in trace)
    record["context_budget"] = budget
    if any(t["action"] != "kept" for t in trace):
        record["context_truncated"] = True
    if window and record["context_total_tokens"] > 0.8 * window:
        record["context_warning"] = f"Context is ~{record['context_total_tokens']:,} tokens, near the model limit of {window:,}"
    return [Message("system", system), Message("user", user)], record


async def _reduce(s: Section, strategy: str, target_tokens: int, query: str, ctx, preview: bool) -> None:
    before = s.tokens
    if strategy == "drop" or target_tokens <= 0:
        s.text, action = "", "dropped"
    elif strategy == "extract":
        s.text, action = extract_relevant(s.text, query, target_tokens), "extracted relevant sections"
    elif strategy == "summarize":
        if preview:
            s.text, action = _truncate_text(s.text, target_tokens), "would be summarized"
        else:
            s.text, action = await ctx.summarize(s.text, target_tokens), "summarized"
    else:
        s.text, action = _truncate_text(s.text, target_tokens), "truncated"
    s.trace.update({"action": action, "strategy": strategy, "tokens_before": before})
