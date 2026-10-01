"""LOCAL TESTING ONLY. A deterministic provider used by automated tests and offline demos.

It never pretends to be a real model: every response is prefixed with "[local-test]" and the UI labels it
"Local test provider (not an AI model)". Disable with ISOCLINE_ENABLE_TEST_PROVIDER=false.

Models:
  echo          – returns a summary of the prompt
  json          – returns data satisfying the requested JSON schema
  tool-user     – calls the first available tool once, then answers
  fail          – always raises 'unavailable' (exercises fallback)
  ratelimit     – always raises 'rate_limit'
  slow-N        – sleeps N seconds before echoing (exercises concurrency/timeouts)
  bad-json      – returns invalid JSON (exercises structured-output repair)
  stubborn      – like json, but picks the LAST enum value and answers false to booleans, so a team manager keeps
                  asking for revisions and peers never declare themselves done (exercises budgets and loop protection)
"""
from __future__ import annotations

import asyncio
import json
import re

from .base import GenerateResult, LLMProvider, ModelInfo, ProviderError, ToolCall

MODELS = ["echo", "json", "tool-user", "scripted", "fail", "ratelimit", "slow-1", "slow-2", "bad-json", "stubborn"]


def sample_for_schema(schema: dict | None, hint: str = "", stubborn: bool = False):
    if not isinstance(schema, dict):
        return "sample"
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: sample_for_schema(v, k, stubborn) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [sample_for_schema(schema.get("items") or {}, hint, stubborn)]
    if t in ("number", "integer"):
        # Deterministic and schema-valid: the default, clamped into [minimum, maximum] when bounds are declared.
        value = 0.5 if t == "number" else 1
        lo = schema.get("minimum", schema.get("exclusiveMinimum"))
        hi = schema.get("maximum", schema.get("exclusiveMaximum"))
        if lo is not None and value < lo:
            value = lo if "minimum" in schema else lo + (1 if t == "integer" else 0.5)
        if hi is not None and value > hi:
            value = hi if "maximum" in schema else hi - (1 if t == "integer" else 0.5)
        return int(value) if t == "integer" else value
    if t == "boolean":
        return not stubborn
    if "enum" in schema:
        return schema["enum"][-1 if stubborn else 0]
    return f"[local-test] {hint or 'value'}"


class LocalTestProvider(LLMProvider):
    id = "local_test"
    name = "Local test provider (not an AI model)"
    requires_key = False
    base_supported_params = ["temperature", "max_tokens", "seed"]

    async def generate(self, messages, model, config, tools=None, response_schema=None, timeout=120):
        prompt = "\n".join(m.content for m in messages if m.role == "user")
        tokens_in = max(1, sum(len(m.content) for m in messages) // 4)
        params, ignored = self.filter_params(model, dict(config), self.model_overrides)
        if model == "fail":
            raise ProviderError("unavailable", "local_test: simulated provider outage")
        if model == "ratelimit":
            raise ProviderError("rate_limit", "local_test: simulated rate limit")
        m = re.match(r"slow-(\d+(?:\.\d+)?)", model)
        if m:
            await asyncio.sleep(float(m.group(1)))
        if model == "scripted":
            # Deterministic capability driver for tests: the user prompt carries a JSON plan
            #   <plan>[{"tool": "fs_write", "args": {...}}, ...]</plan>
            # Each assistant turn issues the next planned tool call; when the plan is exhausted it answers "done".
            done = sum(1 for x in messages if x.role == "tool")
            pm = re.search(r"<plan>(.*?)</plan>", prompt, re.S)
            plan = json.loads(pm.group(1)) if pm else []
            if done < len(plan):
                step = plan[done]
                return GenerateResult(text="", tool_calls=[ToolCall(id=f"call_{done}", name=step["tool"], arguments=step.get("args", {}))],
                                      model=model, input_tokens=tokens_in, output_tokens=8, ignored_params=ignored)
            last = next((x.content for x in reversed(messages) if x.role == "tool"), "")
            return GenerateResult(text=f"done: {last[:400]}", tool_calls=[], model=model, input_tokens=tokens_in, output_tokens=6, ignored_params=ignored)
        if model == "tool-user" and tools and not any(x.role == "tool" for x in messages):
            t = tools[0]
            args = {k: (prompt[:80] if v.get("type") == "string" else 2) for k, v in (t.input_schema.get("properties") or {}).items()}
            if t.name == "calculator":
                args = {"expression": "2 + 2 * 10"}
            return GenerateResult(text="", tool_calls=[ToolCall(id="call_1", name=t.name, arguments=args)], model=model,
                                  input_tokens=tokens_in, output_tokens=10, ignored_params=ignored)
        if model == "bad-json" and response_schema:
            return GenerateResult(text="{not valid json", tool_calls=[], model=model, input_tokens=tokens_in, output_tokens=5)
        if response_schema or model in ("json", "stubborn"):
            data = sample_for_schema(response_schema or {"type": "object", "properties": {"summary": {"type": "string"}}}, stubborn=model == "stubborn")
            text = json.dumps(data)
            return GenerateResult(text=text, tool_calls=[], model=model, input_tokens=tokens_in,
                                  output_tokens=len(text) // 4, structured=data, ignored_params=ignored)
        tool_note = ""
        tool_msgs = [x for x in messages if x.role == "tool"]
        if tool_msgs:
            tool_note = f" Tool result: {tool_msgs[-1].content[:200]}"
        text = f"[local-test] Processed {len(prompt)} characters of input.{tool_note} Excerpt: {(' '.join(prompt.split())[-300:]) if prompt.strip() else '(empty)'}"
        return GenerateResult(text=text, tool_calls=[], model=model, input_tokens=tokens_in,
                              output_tokens=len(text) // 4, ignored_params=ignored)

    async def list_models(self):
        return [ModelInfo(id=m, name=f"{m} (test)", supported_params=self.base_supported_params) for m in MODELS]
