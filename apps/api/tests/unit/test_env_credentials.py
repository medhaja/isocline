"""Self-hosted BYOK: provider keys from environment variables, stored credentials take precedence."""
from __future__ import annotations

import uuid

from isocline.core.security import encrypt_secret
from isocline.db.models import ProviderCredential
from isocline.providers.env_credentials import provider_env, provider_env_configured, tool_secret_env
from isocline.services.credentials import Requester, resolve


def test_provider_env_mapping(monkeypatch):
    for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OLLAMA_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert provider_env("openai") == (None, None) and not provider_env_configured("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")
    assert provider_env("openai")[0] == "sk-env-test" and provider_env_configured("openai")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-second")
    assert provider_env("google")[0] == "g-second"
    monkeypatch.setenv("GEMINI_API_KEY", "g-first")
    assert provider_env("google")[0] == "g-first"  # first variable wins
    assert not provider_env_configured("ollama")  # keyless provider: configured once a base URL is set
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    assert provider_env("ollama") == (None, "http://ollama:11434") and provider_env_configured("ollama")
    assert provider_env("does-not-exist") == (None, None)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    assert tool_secret_env("tavily") == "tvly-x" and tool_secret_env("unknown") is None


async def test_resolution_order(env, monkeypatch):
    db, ws = env["db"], env["workspace"]
    r = Requester(workspace_id=str(ws.id), tool="llm:anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert await resolve(db, r, provider="anthropic") == (None, None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert (await resolve(db, r, provider="anthropic"))[0] == "sk-ant-env"
    # a stored workspace credential wins over the environment
    c = ProviderCredential(workspace_id=ws.id, provider="anthropic", name="Anthropic", hint="…ored",
                           encrypted_value=encrypt_secret("sk-ant-stored"))
    db.add(c)
    await db.commit()
    assert (await resolve(db, r, provider="anthropic"))[0] == "sk-ant-stored"
    # an explicitly selected credential that does not exist never falls back to the environment
    assert await resolve(db, r, credential_id=str(uuid.uuid4())) == (None, None)
