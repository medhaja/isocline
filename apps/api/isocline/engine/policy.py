"""Central policy engine. Pure functions over a policy *snapshot* taken when a run is created, so a run is
governed by one consistent, auditable policy set. Enforcement never depends on model instructions.

Resolution for a given subject/action:
  * mandatory rules from every scope apply; the most restrictive wins (deny > require_approval > allow)
  * among non-mandatory rules, the most specific scope wins (workflow > environment > project > workspace)
  * final effect = the more restrictive of the two; no matching rule = allow
Hence a lower scope can tighten anything but can never weaken a mandatory higher-level restriction.

Rule conditions are declarative (no code execution):
  {"agent_template_in": [...]}, {"agent_template_not_in": [...]}, {"node_key_in": [...]},
  {"arg": "to", "op": "count_gt" | "gt" | "lt" | "eq" | "contains" | "exists", "value": ...}   (tool arguments)
  {"metric": "projected_cost" | "projected_tokens" | "projected_llm_calls", "op": "gt", "value": 2}  (approval rules)
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCOPE_RANK = {"workspace": 1, "project": 2, "environment": 3, "workflow": 4}
EFFECT_RANK = {"allow": 1, "require_approval": 2, "deny": 3}
BUDGET_KEYS = {"max_run_cost": "max_cost", "max_total_tokens": "max_total_tokens", "max_llm_calls": "max_llm_calls",
               "max_tool_calls": "max_tool_calls", "max_parallel_nodes": "max_parallel_nodes",
               "max_runtime_seconds": "max_runtime_seconds"}
WRITE_ACTIONS = {"write", "external_write", "destructive"}


@dataclass
class Decision:
    effect: str  # allow | deny | require_approval
    reason: str
    rule_id: str | None = None
    policy_id: str | None = None
    matched: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"effect": self.effect, "reason": self.reason, "rule_id": self.rule_id, "policy_id": self.policy_id}


# ------------------------------------------------------------------------------------------ classification
def tool_action(tool: str, args: dict | None = None, annotations: dict | None = None) -> str:
    """Classifies what a tool call does. Unknown external tools are treated as external writes."""
    args = args or {}
    if tool == "http_request":
        m = str(args.get("method", "GET")).upper()
        return "read" if m in ("GET", "HEAD", "OPTIONS") else "destructive" if m == "DELETE" else "external_write"
    if tool in ("web_search", "vector_search", "file_reader", "read_artifact"):
        return "read"
    if tool in ("python", "calculator", "json_processor"):
        return "compute"
    if tool.startswith("mcp:"):
        a = annotations or {}
        if a.get("readOnlyHint"):
            return "read"
        if a.get("destructiveHint"):
            return "destructive"
        return "external_write"
    return "external_write"


def has_side_effects(action: str) -> bool:
    return action in WRITE_ACTIONS


# ------------------------------------------------------------------------------------------ matching
def _action_matches(rule_action: str, action: str) -> bool:
    if rule_action in ("*", "", None):
        return True
    if rule_action == "write":
        return action in WRITE_ACTIONS
    return rule_action == action


def _cond_ok(cond: dict, ctx: dict) -> bool:
    if not cond:
        return True
    if "agent_template_in" in cond and ctx.get("agent_template") not in cond["agent_template_in"]:
        return False
    if "agent_template_not_in" in cond and ctx.get("agent_template") in cond["agent_template_not_in"]:
        return False
    if "node_key_in" in cond and ctx.get("node_key") not in cond["node_key_in"]:
        return False
    if "arg" in cond:
        v = (ctx.get("args") or {}).get(cond["arg"])
        return _compare(v, cond.get("op", "exists"), cond.get("value"))
    if "metric" in cond:
        v = (ctx.get("metrics") or {}).get(cond["metric"])
        return v is not None and _compare(v, cond.get("op", "gt"), cond.get("value"))
    return True


def _compare(v: Any, op: str, target: Any) -> bool:
    try:
        if op == "exists":
            return v not in (None, "", [], {})
        if op == "count_gt":
            n = len(v) if isinstance(v, (list, tuple)) else len([x for x in str(v or "").replace(";", ",").split(",") if x.strip()])
            return n > float(target)
        if op == "gt":
            return float(v) > float(target)
        if op == "lt":
            return float(v) < float(target)
        if op == "eq":
            return str(v) == str(target)
        if op == "contains":
            return str(target).lower() in json.dumps(v).lower()
    except (TypeError, ValueError):
        return False
    return False


def _resolve(matches: list[dict], default_reason: str) -> Decision:
    if not matches:
        return Decision("allow", default_reason)
    mandatory = [r for r in matches if r.get("mandatory")]
    optional = [r for r in matches if not r.get("mandatory")]
    best_m = max(mandatory, key=lambda r: EFFECT_RANK[r["effect"]], default=None)
    best_o = None
    if optional:
        top = max(SCOPE_RANK[r["scope_type"]] for r in optional)
        best_o = max((r for r in optional if SCOPE_RANK[r["scope_type"]] == top), key=lambda r: EFFECT_RANK[r["effect"]])
    chosen = max([r for r in (best_m, best_o) if r], key=lambda r: EFFECT_RANK[r["effect"]])
    why = f"{chosen['policy_name']} ({chosen['scope_type']}{', mandatory' if chosen.get('mandatory') else ''})"
    return Decision(chosen["effect"], why, chosen.get("id"), chosen.get("policy_id"), matched=matches)


# ------------------------------------------------------------------------------------------ evaluation
def evaluate_tool(snapshot: list[dict], tool: str, action: str, ctx: dict | None = None) -> Decision:
    ctx = ctx or {}
    matches = [r for r in snapshot if r["kind"] == "tool" and r["effect"] in EFFECT_RANK
               and fnmatch.fnmatchcase(tool, r.get("subject") or "*") and _action_matches(r.get("action") or "*", action)
               and _cond_ok(r.get("condition") or {}, ctx)]
    return _resolve(matches, "No policy restricts this tool")


def evaluate_model(snapshot: list[dict], provider: str, model: str) -> Decision:
    ident = f"{provider}/{model}"
    denies = [r for r in snapshot if r["kind"] == "model" and r["effect"] == "deny" and fnmatch.fnmatchcase(ident, r.get("subject") or "*")]
    if denies:
        return _resolve(denies, "")
    allowlists = [r for r in snapshot if r["kind"] == "model_allowlist"]
    if not allowlists:
        return Decision("allow", "No model policy")
    mandatory = [r for r in allowlists if r.get("mandatory")]
    optional = [r for r in allowlists if not r.get("mandatory")]
    applicable = list(mandatory)
    if optional:
        top = max(SCOPE_RANK[r["scope_type"]] for r in optional)
        applicable += [r for r in optional if SCOPE_RANK[r["scope_type"]] == top]
    for r in applicable:
        globs = r.get("value") or []
        if not any(fnmatch.fnmatchcase(ident, g) for g in globs):
            return Decision("deny", f"{ident} is not on the approved model list of {r['policy_name']} ({r['scope_type']})",
                            r.get("id"), r.get("policy_id"))
    return Decision("allow", "Model is on the approved list")


def budget_clamps(snapshot: list[dict]) -> dict[str, float]:
    """Budgets from policies only ever lower limits (min across all scopes)."""
    out: dict[str, float] = {}
    for r in snapshot:
        if r["kind"] != "budget" or r.get("value") is None:
            continue
        key = BUDGET_KEYS.get(r.get("subject") or "")
        if key:
            v = float(r["value"])
            out[key] = min(out.get(key, v), v)
    return out


def approval_rules_triggered(snapshot: list[dict], metrics: dict) -> list[dict]:
    """Run-level approval conditions (e.g. projected cost > $2) that fire for these plan metrics."""
    return [r for r in snapshot if r["kind"] == "approval" and r["effect"] == "require_approval"
            and _cond_ok(r.get("condition") or {}, {"metrics": metrics})]


def apply_budget_clamps(settings: dict, snapshot: list[dict]) -> dict:
    s = dict(settings)
    for k, v in budget_clamps(snapshot).items():
        cur = s.get(k)
        s[k] = v if cur is None else min(float(cur), v)
        if k != "max_cost":
            s[k] = int(s[k])
    return s


def call_hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
