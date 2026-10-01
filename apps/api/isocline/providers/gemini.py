"""Google Gemini (Generative Language API) adapter."""
from __future__ import annotations

import uuid

from .base import GenerateResult, LLMProvider, Message, ModelInfo, ProviderError, ToolCall
from .http import get_json, post_json

_UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "$schema", "$id", "default", "examples", "title", "const"}
_EFFORT_BUDGET = {"low": 1024, "medium": 8192, "high": 24576}


def sanitize_schema(s):
    if isinstance(s, dict):
        return {k: sanitize_schema(v) for k, v in s.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(s, list):
        return [sanitize_schema(v) for v in s]
    return s


class GeminiProvider(LLMProvider):
    id = "google"
    name = "Google Gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    env_api_key = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    env_base_url = ("GEMINI_BASE_URL",)
    base_supported_params = ["temperature", "top_p", "top_k", "max_tokens", "seed", "frequency_penalty",
                             "presence_penalty", "stop", "reasoning_effort"]

    def headers(self):
        return {"x-goog-api-key": self.cfg.api_key or "", "content-type": "application/json"}

    @staticmethod
    def convert(messages: list[Message]):
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                part = {"functionResponse": {"name": m.name or "tool", "response": {"content": m.content}}}
                if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
            elif m.role == "assistant":
                parts = ([{"text": m.content}] if m.content else []) + [
                    {"functionCall": {"name": t.name, "args": t.arguments}} for t in m.tool_calls]
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content}]})
        return system, contents

    async def generate(self, messages, model, config, tools=None, response_schema=None, timeout=120):
        params, ignored = self.filter_params(model, dict(config), self.model_overrides)
        system, contents = self.convert(messages)
        gen: dict = {}
        mapping = {"temperature": "temperature", "top_p": "topP", "top_k": "topK", "max_tokens": "maxOutputTokens",
                   "seed": "seed", "frequency_penalty": "frequencyPenalty", "presence_penalty": "presencePenalty",
                   "stop": "stopSequences"}
        for k, v in params.items():
            if k in mapping:
                gen[mapping[k]] = v
        if params.get("reasoning_effort"):
            gen["thinkingConfig"] = {"thinkingBudget": _EFFORT_BUDGET[params["reasoning_effort"]]}
        if response_schema and not tools:
            gen["responseMimeType"] = "application/json"
            gen["responseSchema"] = sanitize_schema(response_schema)
        body: dict = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t.name, "description": t.description, "parameters": sanitize_schema(t.input_schema)} for t in tools]}]
        name = model if model.startswith("models/") else f"models/{model}"
        data = await post_json(f"{self.base_url}/{name}:generateContent", body, self.headers(), timeout)
        cands = data.get("candidates") or []
        if not cands:
            fb = data.get("promptFeedback", {})
            raise ProviderError("bad_request", f"No candidates returned (blocked: {fb.get('blockReason', 'unknown')})")
        text, calls = [], []
        for part in (cands[0].get("content") or {}).get("parts", []):
            if "text" in part and not part.get("thought"):
                text.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=fc["name"], arguments=fc.get("args") or {}))
        u = data.get("usageMetadata") or {}
        return GenerateResult(
            text="".join(text), tool_calls=calls, model=data.get("modelVersion", model),
            input_tokens=u.get("promptTokenCount", 0) or 0,
            output_tokens=(u.get("candidatesTokenCount", 0) or 0) + (u.get("thoughtsTokenCount", 0) or 0),
            cached_tokens=u.get("cachedContentTokenCount", 0) or 0, finish_reason=cands[0].get("finishReason"),
            ignored_params=ignored,
        )

    async def list_models(self):
        data = await get_json(f"{self.base_url}/models?pageSize=200", self.headers())
        out = []
        for m in data.get("models", []):
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            mid = m["name"].removeprefix("models/")
            out.append(ModelInfo(id=mid, name=m.get("displayName", mid), context_window=m.get("inputTokenLimit"),
                                 supported_params=self.supported_params(mid)))
        return out
