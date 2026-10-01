"""Ollama native chat API adapter (local models)."""
from __future__ import annotations

import uuid

from .base import GenerateResult, LLMProvider, ModelInfo, ToolCall
from .http import get_json, post_json


class OllamaProvider(LLMProvider):
    id = "ollama"
    name = "Ollama (local)"
    default_base_url = "http://host.docker.internal:11434"
    requires_key = False
    env_base_url = ("OLLAMA_BASE_URL",)
    base_supported_params = ["temperature", "top_p", "top_k", "max_tokens", "seed", "frequency_penalty",
                             "presence_penalty", "stop"]

    def headers(self):
        h = {"content-type": "application/json"}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h

    async def generate(self, messages, model, config, tools=None, response_schema=None, timeout=300):
        params, ignored = self.filter_params(model, dict(config), self.model_overrides)
        opts = {("num_predict" if k == "max_tokens" else k): v for k, v in params.items()}
        msgs = []
        for m in messages:
            if m.role == "tool":
                msgs.append({"role": "tool", "content": m.content, "tool_name": m.name})
            elif m.role == "assistant" and m.tool_calls:
                msgs.append({"role": "assistant", "content": m.content,
                             "tool_calls": [{"function": {"name": t.name, "arguments": t.arguments}} for t in m.tool_calls]})
            else:
                msgs.append({"role": m.role, "content": m.content})
        body: dict = {"model": model, "messages": msgs, "stream": False, "options": opts}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.input_schema}} for t in tools]
        elif response_schema:
            body["format"] = response_schema
        data = await post_json(f"{self.base_url}/api/chat", body, self.headers(), timeout)
        msg = data.get("message") or {}
        calls = [ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=tc["function"]["name"], arguments=tc["function"].get("arguments") or {})
                 for tc in msg.get("tool_calls") or []]
        return GenerateResult(text=msg.get("content") or "", tool_calls=calls, model=data.get("model", model),
                              input_tokens=data.get("prompt_eval_count", 0) or 0, output_tokens=data.get("eval_count", 0) or 0,
                              finish_reason=data.get("done_reason"), ignored_params=ignored)

    async def list_models(self):
        data = await get_json(f"{self.base_url}/api/tags", self.headers())
        return [ModelInfo(id=m["name"], name=m["name"], supported_params=self.supported_params(m["name"]))
                for m in data.get("models", [])]
