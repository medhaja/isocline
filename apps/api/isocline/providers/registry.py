"""Provider registry. Adapters are replaceable: the engine resolves providers only through this module."""
from __future__ import annotations

from isocline.core.config import get_settings

from .anthropic import AnthropicProvider
from .base import LLMProvider, ProviderConfig
from .gemini import GeminiProvider
from .local_test import LocalTestProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatibleProvider, OpenAIProvider, OpenRouterProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GeminiProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "local_test": LocalTestProvider,
}


def provider_classes() -> dict[str, type[LLMProvider]]:
    items = dict(_PROVIDERS)
    if not get_settings().enable_test_provider:
        items.pop("local_test", None)
    return items


def get_provider(provider_id: str, api_key: str | None, base_url: str | None, model_overrides: dict | None = None) -> LLMProvider:
    cls = provider_classes().get(provider_id)
    if cls is None:
        raise KeyError(f"Unknown provider '{provider_id}'")
    return cls(ProviderConfig(api_key=api_key, base_url=base_url), model_overrides)


def register(provider_id: str, cls: type[LLMProvider]) -> None:
    _PROVIDERS[provider_id] = cls
