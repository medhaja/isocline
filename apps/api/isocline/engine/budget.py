"""Hard execution budgets. Every check happens server-side before the guarded operation runs."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from isocline.core.config import get_settings
from isocline.schemas.workflow import WorkflowSettings


class BudgetExceeded(Exception):
    def __init__(self, limit: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.limit = limit
        self.details = details or {}


def effective_settings(ws: WorkflowSettings | dict) -> dict:
    """Clamp workflow-configured limits to server-enforced ceilings."""
    s = get_settings()
    w = ws if isinstance(ws, WorkflowSettings) else WorkflowSettings.model_validate(ws or {})
    return {
        "max_runtime_seconds": min(w.max_runtime_seconds, s.ceiling_runtime_seconds),
        "max_llm_calls": min(w.max_llm_calls, s.ceiling_llm_calls),
        "max_tool_calls": min(w.max_tool_calls, s.ceiling_tool_calls),
        "max_loop_iterations": min(w.max_loop_iterations, s.ceiling_loop_iterations),
        "max_retries_per_node": min(w.max_retries_per_node, s.ceiling_retries),
        "max_parallel_nodes": min(w.max_parallel_nodes, s.ceiling_parallel_nodes),
        "max_cost": min(w.max_cost, s.ceiling_cost_usd) if w.max_cost is not None else s.ceiling_cost_usd,
        "max_total_tokens": min(w.max_total_tokens, s.ceiling_tokens) if w.max_total_tokens else s.ceiling_tokens,
        "cost_limit_user_set": w.max_cost is not None,
        "workflow_memory_enabled": w.workflow_memory_enabled,
        "variables": w.variables,
    }


@dataclass
class Budget:
    limits: dict
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    cost_known: bool = True
    started: float = field(default_factory=time.monotonic)
    elapsed_offset: float = 0.0  # runtime already consumed before a resume
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def elapsed(self) -> float:
        return self.elapsed_offset + (time.monotonic() - self.started)

    def remaining_runtime(self) -> float:
        return self.limits["max_runtime_seconds"] - self.elapsed()

    def check_runtime(self) -> None:
        if self.remaining_runtime() <= 0:
            raise BudgetExceeded("max_runtime", f"Workflow stopped: runtime limit of {self.limits['max_runtime_seconds']}s reached")

    async def reserve_llm_call(self, est_cost: float | None, est_tokens: int) -> None:
        async with self._lock:
            self.check_runtime()
            if self.llm_calls + 1 > self.limits["max_llm_calls"]:
                raise BudgetExceeded("max_llm_calls", f"Workflow stopped: LLM call limit of {self.limits['max_llm_calls']} reached")
            if self.input_tokens + self.output_tokens + est_tokens > self.limits["max_total_tokens"]:
                raise BudgetExceeded("max_total_tokens", f"Workflow stopped: next call would exceed the token budget of {self.limits['max_total_tokens']:,}",
                                     {"used_tokens": self.input_tokens + self.output_tokens, "estimated_next": est_tokens})
            if est_cost is not None and self.cost + est_cost > self.limits["max_cost"]:
                raise BudgetExceeded("max_cost", "Workflow stopped. Next call is estimated to exceed the cost ceiling.", {
                    "configured_ceiling": round(self.limits["max_cost"], 4),
                    "estimated_accumulated_cost": round(self.cost, 4),
                    "estimated_next_call": round(est_cost, 4),
                    "note": "Costs are estimates based on published pricing."})
            self.llm_calls += 1

    async def record_usage(self, input_tokens: int, output_tokens: int, cost: float | None) -> None:
        async with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            if cost is None:
                self.cost_known = False
            else:
                self.cost += cost

    async def reserve_tool_call(self) -> None:
        async with self._lock:
            self.check_runtime()
            if self.tool_calls + 1 > self.limits["max_tool_calls"]:
                raise BudgetExceeded("max_tool_calls", f"Workflow stopped: tool call limit of {self.limits['max_tool_calls']} reached")
            self.tool_calls += 1
