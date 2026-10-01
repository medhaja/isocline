"""Provider-neutral LLM interface. The domain layer only ever sees these types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALL_PARAMS = ["temperature", "top_p", "top_k", "max_tokens", "seed", "frequency_penalty",
              "presence_penalty", "stop", "reasoning_effort"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class GenerateResult:
    text: str
    tool_calls: list[ToolCall]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    finish_reason: str | None = None
    structured: Any = None  # parsed structured output when provider returned it natively
    ignored_params: list[str] = field(default_factory=list)


@dataclass
class ProviderConfig:
    api_key: str | None
    base_url: str | None


class ProviderError(Exception):
    """kind: unavailable | rate_limit | timeout | model_unavailable | auth | bad_request | unknown"""

    FALLBACK_KINDS = {"unavailable", "rate_limit", "timeout", "model_unavailable"}

    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after

    @property
    def fallback_eligible(self) -> bool:
        return self.kind in self.FALLBACK_KINDS

    @property
    def retryable(self) -> bool:
        return self.kind in self.FALLBACK_KINDS or self.kind == "unknown"


def classify_http(status: int, body: str) -> ProviderError:
    b = body[:500]
    if status in (401, 403):
        return ProviderError("auth", f"Authentication failed ({status}): {b}", status)
    if status == 404:
        return ProviderError("model_unavailable", f"Model or endpoint not found: {b}", status)
    if status == 429:
        return ProviderError("rate_limit", f"Rate limited: {b}", status)
    if status == 408:
        return ProviderError("timeout", "Provider timed out", status)
    if status >= 500:
        return ProviderError("unavailable", f"Provider error {status}: {b}", status)
    if "model" in b.lower() and ("not found" in b.lower() or "does not exist" in b.lower()):
        return ProviderError("model_unavailable", b, status)
    return ProviderError("bad_request", f"Request rejected ({status}): {b}", status)


@dataclass
class ModelInfo:
    id: str
    name: str
    context_window: int | None = None
    supported_params: list[str] = field(default_factory=list)
    supports_tools: bool = True
    supports_structured: bool = True


class LLMProvider:
    id: str = ""
    name: str = ""
    default_base_url: str | None = None
    requires_key: bool = True
    base_supported_params: list[str] = []
    # Self-hosted BYOK: environment variables consulted when no credential is stored for this provider in the
    # workspace (see isocline/providers/env_credentials.py). First non-empty variable wins.
    env_api_key: tuple[str, ...] = ()
    env_base_url: tuple[str, ...] = ()

    def __init__(self, cfg: ProviderConfig, model_overrides: dict | None = None):
        self.cfg = cfg
        # Per-model capability overrides from server-side metadata (model_pricing.capabilities)
        self.model_overrides = model_overrides

    @property
    def base_url(self) -> str:
        return (self.cfg.base_url or self.default_base_url or "").rstrip("/")

    def supported_params(self, model: str, overrides: dict | None = None) -> list[str]:
        params = list(self.base_supported_params)
        if overrides:
            params = [p for p in params if p not in overrides.get("unsupported_params", [])]
            params += [p for p in overrides.get("extra_params", []) if p not in params]
        return params

    def filter_params(self, model: str, params: dict, overrides: dict | None = None) -> tuple[dict, list[str]]:
        allowed = set(self.supported_params(model, overrides))
        used = {k: v for k, v in params.items() if v is not None and k in allowed}
        ignored = [k for k, v in params.items() if v is not None and k not in allowed]
        return used, ignored

    async def generate(self, messages: list[Message], model: str, config: dict, tools: list[ToolSpec] | None = None,
                       response_schema: dict | None = None, timeout: float = 120) -> GenerateResult:
        raise NotImplementedError

    async def list_models(self) -> list[ModelInfo]:
        return []
