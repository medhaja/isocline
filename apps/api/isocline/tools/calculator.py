"""Safe arithmetic evaluator (AST whitelist). Never uses eval()."""
from __future__ import annotations

import ast
import math
import operator

from .base import Tool, ToolError

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp, "abs": abs, "round": round,
          "min": min, "max": max, "sum": lambda *a: sum(a[0]) if len(a) == 1 and isinstance(a[0], list) else sum(a),
          "floor": math.floor, "ceil": math.ceil, "sin": math.sin, "cos": math.cos, "tan": math.tan, "pow": pow}
_CONSTS = {"pi": math.pi, "e": math.e}


def safe_eval(expr: str) -> float | int:
    if len(expr) > 500:
        raise ToolError("Expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ToolError(f"Invalid expression: {e.msg}") from e

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(r) > 1000 or abs(l) > 1e12):
                raise ToolError("Exponent too large")
            return _BIN[type(n.op)](l, r)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY:
            return _UNARY[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in _CONSTS:
            return _CONSTS[n.id]
        if isinstance(n, ast.List):
            return [ev(x) for x in n.elts]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ToolError(f"Unsupported expression element: {type(n).__name__}")

    try:
        return ev(tree)
    except ZeroDivisionError as e:
        raise ToolError("Division by zero") from e
    except (ValueError, OverflowError, TypeError) as e:
        raise ToolError(str(e)) from e


class CalculatorTool(Tool):
    name = "calculator"
    description = "Evaluate an arithmetic expression. Supports + - * / // % **, parentheses, sqrt, log, exp, min, max, round, pi, e."
    input_schema = {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}

    async def execute(self, args, ctx):
        return {"expression": args.get("expression"), "result": safe_eval(str(args.get("expression", "")))}
