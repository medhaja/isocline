"""One-off LLM calls outside workflow runs (AI workflow generator, optimizer, LLM-judge evaluations).
Uses the same provider abstraction, credentials and pricing as the engine and records usage by purpose."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError
from isocline.core.logging import redact_text
from isocline.core.security import decrypt_secret
from isocline.db.models import ModelPricing, ProviderCredential, UsageRecord
from isocline.engine.pricing import estimate_cost
from isocline.engine.structured import StructuredOutputError, extract_json
from isocline.providers.base import Message, ProviderError
from isocline.providers.registry import get_provider, provider_classes


@dataclass
class LLMResult:
    text: str
    data: Any
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


async def pick_default_model(db: AsyncSession, workspace_id) -> dict | None:
    """First configured provider credential, preferring hosted providers; None if nothing is configured."""
    creds = (await db.execute(select(ProviderCredential).where(ProviderCredential.workspace_id == workspace_id)
                              .order_by(ProviderCredential.created_at))).scalars().all()
    classes = provider_classes()
    from isocline.providers.env_credentials import provider_env_configured
    for c in creds:
        if c.provider in classes and c.provider != "local_test":
            m = (await db.execute(select(ModelPricing.model).where(ModelPricing.provider == c.provider, ModelPricing.active == True)  # noqa: E712
                                  .order_by(ModelPricing.input_per_mtok.desc()).limit(1))).scalar()
            if m:
                return {"provider": c.provider, "model": m, "credential_id": str(c.id)}
    for pid in classes:  # nothing stored: providers configured through the environment
        if pid != "local_test" and provider_env_configured(pid):
            m = (await db.execute(select(ModelPricing.model).where(ModelPricing.provider == pid, ModelPricing.active == True)  # noqa: E712
                                  .order_by(ModelPricing.input_per_mtok.desc()).limit(1))).scalar()
            if m:
                return {"provider": pid, "model": m}
    return None


async def complete(db: AsyncSession, workspace_id, ref: dict, system: str, user: str, *, json_schema: dict | None = None,
                   purpose: str, project_id=None, temperature: float | None = 0.2, max_tokens: int = 4000,
                   timeout: float = 120) -> LLMResult:
    provider_id, model = ref.get("provider"), ref.get("model")
    if not provider_id or not model:
        raise AppError(400, "no_model", "Choose a provider and model for this action")
    q = select(ProviderCredential).where(ProviderCredential.workspace_id == workspace_id)
    q = q.where(ProviderCredential.id == uuid.UUID(str(ref["credential_id"]))) if ref.get("credential_id") else q.where(ProviderCredential.provider == provider_id)
    cred = (await db.execute(q.order_by(ProviderCredential.created_at).limit(1))).scalar_one_or_none()
    api_key = decrypt_secret(cred.encrypted_value) if cred and cred.encrypted_value else None
    base_url = cred.base_url if cred else None
    if cred is None and not ref.get("credential_id"):
        from isocline.providers.env_credentials import provider_env
        api_key, base_url = provider_env(provider_id)
    pricing_row = (await db.execute(select(ModelPricing).where(ModelPricing.provider == provider_id, ModelPricing.model == model))).scalar_one_or_none()
    try:
        prov = get_provider(provider_id, api_key, base_url, pricing_row.capabilities if pricing_row else None)
    except KeyError as e:
        raise AppError(400, "unknown_provider", str(e)) from e
    if prov.requires_key and not api_key:
        raise AppError(400, "credential_missing", f"Add a {prov.name} API key under Providers, or set it in the environment "
                       f"({' / '.join(type(prov).env_api_key) or 'no variable'})")
    params = {"max_tokens": max_tokens}
    if temperature is not None:
        params["temperature"] = temperature
    try:
        res = await asyncio.wait_for(prov.generate([Message("system", system), Message("user", user)], model, params,
                                                   response_schema=json_schema, timeout=timeout), timeout=timeout + 5)
    except asyncio.TimeoutError as e:
        raise AppError(504, "model_timeout", "The model did not respond in time") from e
    except ProviderError as e:
        raise AppError(502, "provider_error", redact_text(str(e))[:500]) from e
    pricing = None
    if pricing_row:
        pricing = {"input_per_mtok": pricing_row.input_per_mtok, "output_per_mtok": pricing_row.output_per_mtok,
                   "cached_input_per_mtok": pricing_row.cached_input_per_mtok}
    cost = estimate_cost(pricing, res.input_tokens, res.output_tokens, res.cached_tokens)
    db.add(UsageRecord(workspace_id=workspace_id, project_id=project_id, provider=provider_id, model=res.model or model,
                       input_tokens=res.input_tokens, output_tokens=res.output_tokens, cached_tokens=res.cached_tokens,
                       cost_usd=cost, purpose=purpose))
    await db.commit()
    data = None
    if json_schema is not None:
        data = res.structured
        if data is None:
            try:
                data = extract_json(res.text)
            except StructuredOutputError as e:
                raise AppError(502, "invalid_model_output", "The model did not return valid JSON") from e
    return LLMResult(res.text, data, provider_id, res.model or model, res.input_tokens, res.output_tokens, cost)
