"""Self-hosted BYOK: provider credentials from environment variables.

Resolution order for a model call (see services/credentials.resolve and services/llm.complete):
  1. a credential explicitly selected on the node (credential_id)          -> only that credential
  2. a credential stored in the workspace for the provider (encrypted)     -> first one whose scope admits the call
  3. the provider's environment variables (LLMProvider.env_api_key/env_base_url)

Environment credentials apply to every workspace on the installation (the OSS edition is single-tenant). Their values
are never written to the database, to workflow JSON or to exports, and they are redacted from traces like any other
secret the harness releases.

Named tool secrets (web search) follow the same rule with TOOL_SECRET_ENV.
"""
from __future__ import annotations

import os

# Secrets that built-in tools request by name (ctx.get_secret("tavily")).
TOOL_SECRET_ENV: dict[str, tuple[str, ...]] = {
    "tavily": ("TAVILY_API_KEY",),
    "brave": ("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"),
}


def _first(names: tuple[str, ...]) -> str | None:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return None


def provider_env(provider_id: str) -> tuple[str | None, str | None]:
    """(api_key, base_url) from the environment for a registered provider; (None, None) if nothing is set."""
    from isocline.providers.registry import provider_classes
    cls = provider_classes().get(provider_id)
    if cls is None:
        return None, None
    return _first(cls.env_api_key), _first(cls.env_base_url)


def provider_env_configured(provider_id: str) -> bool:
    """True when the environment provides what this provider needs to be called."""
    from isocline.providers.registry import provider_classes
    cls = provider_classes().get(provider_id)
    if cls is None:
        return False
    key, base = provider_env(provider_id)
    if cls.requires_key:
        return bool(key)
    return bool(key or base)


def tool_secret_env(name: str) -> str | None:
    return _first(TOOL_SECRET_ENV.get(name.lower(), ()))
