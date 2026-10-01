"""OpenAI Chat Completions adapter. Also powers OpenRouter and generic OpenAI-compatible endpoints."""
from __future__ import annotations

import json
import re

from .base import GenerateResult, LLMProvider, Message, ModelInfo, ProviderError, ToolCall
from .http import get_json, parse_args, post_json

_REASONING = re.compile(r"^(o\d|gpt-([5-9]|\d{2,}))", re.I)  # o-series and gpt-5 or later


def to_openai_messages(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append({
                "role": "assistant", "content": m.content or None,
                "tool_calls": [{"id": t.id, "type": "function",
                                "function": {"name": t.name, "arguments": json.dumps(t.arguments)}} for t in m.tool_calls],
            })
        else:
            out.append({"role": m.role, "content": m.content})
    return out


class OpenAICompatibleProvider(LLMProvider):
    id = "openai_compatible"
    name = "OpenAI-compatible endpoint"
    default_base_url = None
    requires_key = False
    env_api_key = ("OPENAI_COMPATIBLE_API_KEY",)
    env_base_url = ("OPENAI_COMPATIBLE_BASE_URL",)
    base_supported_params = ["temperature", "top_p", "max_tokens", "seed", "frequency_penalty", "presence_penalty", "stop"]
    extra_headers: dict = {}

    def headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.extra_headers}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h

    def build_payload(self, messages, model, params, tools, response_schema) -> dict:
        p: dict = {"model": model, "messages": to_openai_messages(messages)}
        if "max_tokens" in params:
            p["max_tokens"] = params.pop("max_tokens")
        p.update(params)
        if tools:
            p["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                             "parameters": t.input_schema}} for t in tools]
        if response_schema and not tools:
            p["response_format"] = {"type": "json_schema",
                                    "json_schema": {"name": "output", "schema": response_schema, "strict": False}}
        return p

    async def generate(self, messages, model, config, tools=None, response_schema=None, timeout=120) -> GenerateResult:
        if not self.base_url:
            raise ProviderError("bad_request", "No base URL configured for this endpoint")
        params, ignored = self.filter_params(model, dict(config), self.model_overrides)
        payload = self.build_payload(messages, model, params, tools, response_schema)
        try:
            data = await post_json(f"{self.base_url}/chat/completions", payload, self.headers(), timeout)
        except ProviderError as e:
            msg = str(e)
            if e.kind == "bad_request" and tools and payload.get("reasoning_effort") != "none" and "reasoning_effort" in msg:
                # Some reasoning models reject function tools combined with reasoning (their own default applies when
                # none is sent) on /chat/completions -- OpenAI: "set reasoning_effort to 'none'". Tool use matters more
                # than the effort hint: retry once with "none" and report the adjustment in the trace.
                payload["reasoning_effort"] = "none"
                ignored = [*ignored, "reasoning_effort (set to 'none': not supported with tools on this model)"]
                data = await post_json(f"{self.base_url}/chat/completions", payload, self.headers(), timeout)
            # Some compatible servers do not support json_schema; retry once with json_object mode.
            elif response_schema and e.kind == "bad_request" and "response_format" in payload:
                payload["response_format"] = {"type": "json_object"}
                data = await post_json(f"{self.base_url}/chat/completions", payload, self.headers(), timeout)
            else:
                raise
        return self.parse(data, model, ignored)

    def parse(self, data: dict, model: str, ignored: list[str]) -> GenerateResult:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("unavailable", f"Empty response: {str(data)[:300]}")
        msg = choices[0].get("message") or {}
        calls = [ToolCall(id=tc.get("id") or f"call_{i}", name=tc["function"]["name"], arguments=parse_args(tc["function"].get("arguments")))
                 for i, tc in enumerate(msg.get("tool_calls") or [])]
        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        return GenerateResult(
            text=msg.get("content") or "", tool_calls=calls, model=data.get("model") or model,
            input_tokens=usage.get("prompt_tokens", 0) or 0, output_tokens=usage.get("completion_tokens", 0) or 0,
            cached_tokens=cached, finish_reason=choices[0].get("finish_reason"), ignored_params=ignored,
        )

    async def list_models(self) -> list[ModelInfo]:
        if not self.base_url:
            return []
        data = await get_json(f"{self.base_url}/models", self.headers())
        return [ModelInfo(id=m["id"], name=m.get("name") or m["id"], context_window=m.get("context_length"),
                          supported_params=self.supported_params(m["id"])) for m in data.get("data", [])]


class OpenAIProvider(OpenAICompatibleProvider):
    id = "openai"
    name = "OpenAI"
    default_base_url = "https://api.openai.com/v1"
    requires_key = True
    env_api_key = ("OPENAI_API_KEY",)
    env_base_url = ("OPENAI_BASE_URL",)

    def supported_params(self, model, overrides=None):
        if _REASONING.match(model):
            params = ["max_tokens", "seed", "reasoning_effort", "stop"]
        else:
            params = ["temperature", "top_p", "max_tokens", "seed", "frequency_penalty", "presence_penalty", "stop"]
        if overrides:
            params = [p for p in params if p not in overrides.get("unsupported_params", [])]
            params += [p for p in overrides.get("extra_params", []) if p not in params]
        return params

    def build_payload(self, messages, model, params, tools, response_schema):
        p = super().build_payload(messages, model, params, tools, response_schema)
        if "max_tokens" in p:
            p["max_completion_tokens"] = p.pop("max_tokens")
        if _REASONING.match(model):
            p["messages"] = [{**m, "role": "developer"} if m["role"] == "system" else m for m in p["messages"]]
        return p

    async def list_models(self):
        data = await get_json(f"{self.base_url}/models", self.headers())
        keep = re.compile(r"^(gpt|o\d|chatgpt)", re.I)
        skip = re.compile(r"(audio|realtime|tts|transcribe|image|search|embedding|instruct)", re.I)
        return sorted([ModelInfo(id=m["id"], name=m["id"], supported_params=self.supported_params(m["id"]))
                       for m in data.get("data", []) if keep.match(m["id"]) and not skip.search(m["id"])], key=lambda x: x.id)


class OpenRouterProvider(OpenAICompatibleProvider):
    id = "openrouter"
    name = "OpenRouter"
    default_base_url = "https://openrouter.ai/api/v1"
    requires_key = True
    env_api_key = ("OPENROUTER_API_KEY",)
    base_supported_params = ["temperature", "top_p", "top_k", "max_tokens", "seed", "frequency_penalty",
                             "presence_penalty", "stop", "reasoning_effort"]
    extra_headers = {"X-Title": "Isocline"}

    def build_payload(self, messages, model, params, tools, response_schema):
        effort = params.pop("reasoning_effort", None)
        p = super().build_payload(messages, model, params, tools, response_schema)
        if effort:
            p["reasoning"] = {"effort": effort}
        return p
