"""Anthropic Messages API adapter. Structured output uses a forced tool, which is Anthropic's native mechanism."""
from __future__ import annotations

from .base import GenerateResult, LLMProvider, Message, ModelInfo, ToolCall
from .http import get_json, post_json

_OUTPUT_TOOL = "emit_structured_output"
_EFFORT_BUDGET = {"low": 2048, "medium": 8192, "high": 24576}


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    name = "Anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    env_api_key = ("ANTHROPIC_API_KEY",)
    env_base_url = ("ANTHROPIC_BASE_URL",)
    base_supported_params = ["temperature", "top_p", "top_k", "max_tokens", "stop", "reasoning_effort"]

    def headers(self):
        return {"x-api-key": self.cfg.api_key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}

    @staticmethod
    def convert(messages: list[Message]) -> tuple[str, list[dict]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == "assistant" and m.tool_calls:
                content = ([{"type": "text", "text": m.content}] if m.content else []) + [
                    {"type": "tool_use", "id": t.id, "name": t.name, "input": t.arguments} for t in m.tool_calls]
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": m.role, "content": m.content or "(empty)"})
        return system, out

    async def generate(self, messages, model, config, tools=None, response_schema=None, timeout=120):
        params, ignored = self.filter_params(model, dict(config), self.model_overrides)
        system, msgs = self.convert(messages)
        p: dict = {"model": model, "messages": msgs, "max_tokens": params.pop("max_tokens", 4096)}
        if system:
            p["system"] = system
        if "stop" in params:
            p["stop_sequences"] = params.pop("stop")
        effort = params.pop("reasoning_effort", None)
        p.update(params)
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in (tools or [])]
        forced = False
        if response_schema:
            schema = response_schema if response_schema.get("type") == "object" else {"type": "object", "properties": {"value": response_schema}}
            tool_defs.append({"name": _OUTPUT_TOOL, "description": "Return the final answer in the required structure.", "input_schema": schema})
            if not tools:
                p["tool_choice"] = {"type": "tool", "name": _OUTPUT_TOOL}
                forced = True
        if effort and not forced:
            budget = _EFFORT_BUDGET[effort]
            p["thinking"] = {"type": "enabled", "budget_tokens": budget}
            p["max_tokens"] = max(p["max_tokens"], budget + 1024)
            p.pop("temperature", None); p.pop("top_k", None); p.pop("top_p", None)
        elif effort:
            ignored.append("reasoning_effort")
        if tool_defs:
            p["tools"] = tool_defs
        data = await post_json(f"{self.base_url}/messages", p, self.headers(), timeout)
        text_parts, calls, structured = [], [], None
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                if block["name"] == _OUTPUT_TOOL:
                    structured = block.get("input")
                    if response_schema and response_schema.get("type") != "object" and isinstance(structured, dict):
                        structured = structured.get("value")
                else:
                    calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
        usage = data.get("usage") or {}
        return GenerateResult(
            text="".join(text_parts), tool_calls=calls, model=data.get("model", model), structured=structured,
            input_tokens=(usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0),
            output_tokens=usage.get("output_tokens", 0) or 0, cached_tokens=usage.get("cache_read_input_tokens", 0) or 0,
            finish_reason=data.get("stop_reason"), ignored_params=ignored,
        )

    async def list_models(self):
        data = await get_json(f"{self.base_url}/models?limit=100", self.headers())
        return [ModelInfo(id=m["id"], name=m.get("display_name") or m["id"], supported_params=self.supported_params(m["id"]))
                for m in data.get("data", [])]
