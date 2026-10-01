"""Node-result cache: identity and safety.

Cache key = hash of everything that can change the result: harness version, node type, the effective config
(minus reliability knobs), the fully rendered model input, model, tool configuration and knowledge-base content
versions. The *signature* is the same identity without the request text; semantic lookup only considers entries
with an identical signature, so a similar question never reuses an answer produced under a different prompt,
model or toolset.

Never cached: side-effecting nodes (writes, external calls with side effects, MCP tools that are not read-only,
contracts declaring side effects), waits, approvals, sub-workflows, inputs/outputs and logic."""
from __future__ import annotations

import hashlib
import json
from typing import Any

HARNESS_CACHE_VERSION = "v2.1"
CACHEABLE_TYPES = {"agent", "tool_web_search", "tool_python", "tool_calculator", "tool_json", "tool_vector_search",
                   "tool_file_reader", "tool_http"}
IGNORED_CONFIG = {"retry", "on_failure", "timeout_seconds", "fallbacks"}


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def cache_safety(node, config: dict, resolved_args: dict | None = None) -> tuple[bool, str]:
    """(cacheable, reason). Conservative: anything that might have side effects is excluded."""
    if node.type not in CACHEABLE_TYPES:
        return False, f"{node.type} nodes are never cached"
    if node.contract and node.contract.side_effects not in ("none", "read"):
        return False, f"contract declares side effects ({node.contract.side_effects})"
    if node.type == "tool_http":
        method = str((resolved_args or config.get("arguments") or {}).get("method", "GET")).upper()
        if method not in ("GET", "HEAD"):
            return False, f"HTTP {method} has side effects"
    if node.type == "agent":
        tools = config.get("tools") or []
        risky = [t for t in tools if t == "http_request" or t.startswith("mcp:")]
        if risky:
            return False, f"agent can call side-effecting tools ({', '.join(risky)})"
        if (config.get("memory") or {}).get("write_workflow_memory"):
            return False, "agent writes workflow memory"
    if node.harness.compensation is not None:
        return False, "node declares a compensation (it has side effects)"
    return True, ""


def identity(node, config: dict, resolved: dict, kb_versions: dict | None = None) -> tuple[str, str, str]:
    """Returns (cache_key, signature, key_text)."""
    cfg = {k: v for k, v in (config or {}).items() if k not in IGNORED_CONFIG}
    base = {"v": HARNESS_CACHE_VERSION, "type": node.type, "config": cfg, "contract": node.contract.model_dump() if node.contract else None,
            "kb": kb_versions or {}}
    request = resolved.get("request_text", "")
    rest = {k: v for k, v in resolved.items() if k != "request_text"}
    signature = _h({**base, **rest, "_sig": True})
    key = _h({**base, **rest, "request": request})
    return key, signature, request
