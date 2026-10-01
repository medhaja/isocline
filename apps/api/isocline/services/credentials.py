"""Run-time credential resolution.

Order for a model call, tool secret or MCP token:
  1. an explicitly selected credential (credential_id)      -> only that one; never falls back
  2. a credential stored in the workspace (Fernet-encrypted) -> by provider id or by name
  3. environment variables declared by the provider / tool  -> see isocline/providers/env_credentials.py

Values are decrypted only here, at call time, and the executor adds them to the run's redaction set.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.security import decrypt_secret
from isocline.db.models import ProviderCredential


@dataclass
class Requester:
    workspace_id: str
    tool: str = ""


def _from_environment(*, name: str | None, credential_id: str | None, provider: str | None) -> tuple[str | None, str | None]:
    if credential_id:
        return None, None
    from isocline.providers.env_credentials import provider_env, tool_secret_env
    if provider:
        return provider_env(provider)
    if name:
        key, base = provider_env(name)
        return (key or tool_secret_env(name)), base
    return None, None


async def resolve(db: AsyncSession, r: Requester, *, name: str | None = None, credential_id: str | None = None,
                  provider: str | None = None) -> tuple[str | None, str | None]:
    """(secret value or None, base_url or None)."""
    ws = uuid.UUID(str(r.workspace_id))
    q = select(ProviderCredential).where(ProviderCredential.workspace_id == ws)
    if credential_id:
        try:
            q = q.where(ProviderCredential.id == uuid.UUID(str(credential_id)))
        except ValueError:
            return None, None
    elif name:
        q = q.where((ProviderCredential.name == name) | (ProviderCredential.provider == name))
    elif provider:
        q = q.where(ProviderCredential.provider == provider)
    else:
        return None, None
    c = (await db.execute(q.order_by(ProviderCredential.created_at).limit(1))).scalar_one_or_none()
    if c is None:
        return _from_environment(name=name, credential_id=credential_id, provider=provider)
    value = decrypt_secret(c.encrypted_value) if c.encrypted_value else None
    return value, c.base_url
