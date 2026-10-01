"""Variable resolution ({{research.output.summary}}) and rule evaluation. No eval() anywhere."""
from __future__ import annotations

import json
import re
from typing import Any

from .graph import VAR_RE

_PATH_TOKEN = re.compile(r"\.([\w\-]+)|\[(\d+)\]")
_MISSING = object()


class Scope:
    """Read-only view of run state used for template resolution."""

    def __init__(self, run_input: dict, outputs_by_key: dict[str, Any], variables: dict | None = None,
                 loop: dict | None = None, memory: dict | None = None, run_meta: dict | None = None):
        self.root: dict[str, Any] = {
            "input": run_input or {},
            "vars": variables or {},
            "loop": loop or {},
            "memory": memory or {},
            "run": run_meta or {},
        }
        for k, v in outputs_by_key.items():
            self.root[k] = {"output": v}

    def child(self, **extra) -> "Scope":
        s = Scope.__new__(Scope)
        s.root = {**self.root, **extra}
        return s

    def lookup(self, head: str, path: str) -> Any:
        if head not in self.root:
            return _MISSING
        cur = self.root[head]
        tokens = [(m.group(1), m.group(2)) for m in _PATH_TOKEN.finditer(path or "")]
        # Shortcut: {{research.summary}} == {{research.output.summary}}
        if head not in ("input", "vars", "loop", "memory", "run") and tokens and tokens[0][0] != "output":
            tokens = [("output", None)] + tokens
        for name, idx in tokens:
            if isinstance(cur, str) and name is not None:
                try:
                    cur = json.loads(cur)
                except (ValueError, TypeError):
                    return _MISSING
            if name is not None:
                if isinstance(cur, dict) and name in cur:
                    cur = cur[name]
                else:
                    return _MISSING
            else:
                i = int(idx)
                if isinstance(cur, list) and -len(cur) <= i < len(cur):
                    cur = cur[i]
                else:
                    return _MISSING
        return cur


def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, indent=2, default=str)


def resolve_value(expr: str, scope: Scope) -> Any:
    """If expr is exactly one {{var}}, return the raw value (keeps types). Otherwise render text."""
    if not isinstance(expr, str):
        return expr
    s = expr.strip()
    m = VAR_RE.fullmatch(s)
    if m:
        v = scope.lookup(m.group(1), m.group(2))
        return None if v is _MISSING else v
    if "{{" in s:
        return render(expr, scope)
    return expr


def render(template: str, scope: Scope, strict: bool = False) -> str:
    def rep(m: re.Match) -> str:
        v = scope.lookup(m.group(1), m.group(2))
        if v is _MISSING:
            if strict:
                raise KeyError(m.group(0))
            return ""
        return to_text(v)
    return VAR_RE.sub(rep, template or "")


def resolve_deep(obj: Any, scope: Scope) -> Any:
    if isinstance(obj, str):
        return resolve_value(obj, scope)
    if isinstance(obj, dict):
        return {k: resolve_deep(v, scope) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_deep(v, scope) for v in obj]
    return obj


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _coerce_literal(v: Any) -> Any:
    if isinstance(v, str):
        t = v.strip()
        if t.lower() in ("true", "false"):
            return t.lower() == "true"
        if t.lower() in ("null", "none"):
            return None
        n = _num(t)
        if n is not None:
            return n
    return v


def compare(left: Any, op: str, right: Any) -> bool:
    if op == "exists":
        return left is not None and left != ""
    if op == "not_exists":
        return left is None or left == ""
    right = _coerce_literal(right)
    if op == "contains":
        if isinstance(left, (list, tuple)):
            return right in left or str(right) in [str(x) for x in left]
        if isinstance(left, dict):
            return str(right) in left
        return str(right).lower() in to_text(left).lower()
    if op in (">", ">=", "<", "<="):
        a, b = _num(left), _num(right)
        if a is None or b is None:
            return False
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if op in ("==", "!="):
        a_n, b_n = _num(left), _num(right)
        if isinstance(right, bool) or isinstance(left, bool):
            eq = str(left).lower() == str(right).lower()
        elif a_n is not None and b_n is not None:
            eq = a_n == b_n
        elif right is None or left is None:
            eq = left is None and right is None
        else:
            eq = to_text(left).strip() == to_text(right).strip()
        return eq if op == "==" else not eq
    raise ValueError(f"Unsupported operator {op}")


def evaluate_rule(rule: dict, scope: Scope) -> tuple[bool, Any, Any]:
    left = resolve_value(rule.get("left", ""), scope)
    right = rule.get("right")
    if isinstance(right, str):
        right = resolve_value(right, scope)
    return compare(left, rule.get("operator", "=="), right), left, right
