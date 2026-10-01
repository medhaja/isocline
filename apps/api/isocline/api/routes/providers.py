from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, membership, parse_uuid
from isocline.core.config import get_settings
from isocline.core.errors import bad_request, forbidden, not_found
from isocline.core.logging import redact_text
from isocline.core.security import decrypt_secret, encrypt_secret
from isocline.db.models import ModelPricing, ProviderCredential, User
from isocline.db.session import get_db
from isocline.providers.base import ProviderError
from isocline.providers.registry import get_provider, provider_classes
from isocline.services.audit import audit
from isocline.tools.ssrf import check_url

router = APIRouter(tags=["providers"])

ALL_PARAMS = ["temperature", "top_p", "top_k", "max_tokens", "seed", "frequency_penalty", "presence_penalty", "stop", "reasoning_effort"]
SECRET_KINDS = {"custom", "search"}  # non-LLM secrets: CUSTOM_API_KEYS, tavily/brave keys, HTTP tool secrets


class CredentialIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    value: str | None = Field(default=None, max_length=20000)
    base_url: str | None = Field(default=None, max_length=500)


class CredentialPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    value: str | None = Field(default=None, max_length=20000)  # rotation
    base_url: str | None = Field(default=None, max_length=500)


class PricingRow(BaseModel):
    provider: str
    model: str
    display_name: str = ""
    context_window: int | None = None
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cached_input_per_mtok: float | None = None
    capabilities: dict = Field(default_factory=dict)
    active: bool = True


def cred_out(c: ProviderCredential) -> dict:
    # Never returns the value. `hint` is the last 4 characters only.
    return dump(c, "id", "workspace_id", "provider", "name", "hint", "base_url", "created_at", has_value=c.encrypted_value is not None)


@router.get("/providers")
async def list_providers(workspace_id: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    configured: set[str] = set()
    if workspace_id:
        await membership(db, user, workspace_id)
        configured = set((await db.execute(select(ProviderCredential.provider).where(
            ProviderCredential.workspace_id == parse_uuid(workspace_id)))).scalars().all())
    from isocline.providers.env_credentials import provider_env_configured
    # env_configured reports *that* the environment provides a credential, never its value or variable contents.
    return [{"id": pid, "name": cls.name, "requires_key": cls.requires_key, "default_base_url": cls.default_base_url,
             "configured": pid in configured or not cls.requires_key or provider_env_configured(pid),
             "has_credential": pid in configured, "env_configured": provider_env_configured(pid),
             "env_vars": list(cls.env_api_key) + list(cls.env_base_url),
             "is_test": pid == "local_test", "all_params": ALL_PARAMS}
            for pid, cls in provider_classes().items()]


async def _catalog(db: AsyncSession, provider: str) -> dict[str, ModelPricing]:
    rows = (await db.execute(select(ModelPricing).where(ModelPricing.provider == provider, ModelPricing.active == True))).scalars().all()  # noqa: E712
    return {r.model: r for r in rows}


@router.get("/providers/{provider_id}/models")
async def list_models(provider_id: str, workspace_id: str | None = None, credential_id: str | None = None,
                      user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Model catalog: live from the provider when a credential is available, merged with server-side metadata."""
    cls = provider_classes().get(provider_id)
    if cls is None:
        raise not_found("Provider")
    api_key = base_url = None
    if workspace_id:
        await membership(db, user, workspace_id)
        q = select(ProviderCredential).where(ProviderCredential.workspace_id == parse_uuid(workspace_id))
        q = q.where(ProviderCredential.id == parse_uuid(credential_id)) if credential_id else q.where(ProviderCredential.provider == provider_id)
        c = (await db.execute(q.order_by(ProviderCredential.created_at).limit(1))).scalar_one_or_none()
        if c:
            api_key = decrypt_secret(c.encrypted_value) if c.encrypted_value else None
            base_url = c.base_url
    if api_key is None and base_url is None and not credential_id:
        from isocline.providers.env_credentials import provider_env
        api_key, base_url = provider_env(provider_id)
    catalog = await _catalog(db, provider_id)
    prov = get_provider(provider_id, api_key, base_url)
    live, source, warning = [], "catalog", None
    if api_key or not cls.requires_key:
        try:
            if base_url and provider_id not in ("ollama", "openai_compatible"):
                await check_url(base_url)  # hosted providers must never be pointed at internal addresses
            live = await asyncio.wait_for(prov.list_models(), timeout=8)
            source = "provider"
        except Exception as e:
            warning = f"Could not list models from {cls.name}: {redact_text(str(e))[:200]}"
    else:
        warning = f"Add a {cls.name} credential to load its live model list"
    models: dict[str, dict] = {}
    for m in live:
        meta = catalog.get(m.id)
        models[m.id] = {"id": m.id, "name": (meta.display_name if meta and meta.display_name else m.name),
                        "context_window": (meta.context_window if meta else None) or m.context_window,
                        "supported_params": prov.supported_params(m.id, meta.capabilities if meta else None),
                        "pricing": _price(meta), "source": "provider"}
    for mid, meta in catalog.items():
        if mid not in models:
            models[mid] = {"id": mid, "name": meta.display_name or mid, "context_window": meta.context_window,
                           "supported_params": prov.supported_params(mid, meta.capabilities), "pricing": _price(meta),
                           "source": "catalog"}
    return {"provider": provider_id, "source": source, "warning": warning, "models": sorted(models.values(), key=lambda x: x["id"])}


def _price(meta: ModelPricing | None) -> dict | None:
    if not meta or meta.input_per_mtok is None:
        return None
    return {"input_per_mtok": meta.input_per_mtok, "output_per_mtok": meta.output_per_mtok,
            "cached_input_per_mtok": meta.cached_input_per_mtok, "is_estimate": True}


@router.get("/providers/{provider_id}/params")
async def supported_params(provider_id: str, model: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if provider_id not in provider_classes():
        raise not_found("Provider")
    meta = (await _catalog(db, provider_id)).get(model)
    return {"supported_params": get_provider(provider_id, None, None).supported_params(model, meta.capabilities if meta else None)}


# ------------------------------------------------------------------ credentials (secrets vault)
@router.get("/workspaces/{workspace_id}/credentials")
async def list_credentials(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(ProviderCredential).where(ProviderCredential.workspace_id == parse_uuid(workspace_id))
                             .order_by(ProviderCredential.created_at))).scalars().all()
    return [cred_out(c) for c in rows]


@router.post("/workspaces/{workspace_id}/credentials", status_code=201)
async def create_credential(workspace_id: str, body: CredentialIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id, "admin")
    classes = provider_classes()
    if body.provider not in classes and body.provider not in SECRET_KINDS and body.provider not in ("tavily", "brave"):
        raise bad_request(f"Unknown provider '{body.provider}'")
    cls = classes.get(body.provider)
    if cls and cls.requires_key and not body.value:
        raise bad_request("An API key is required for this provider")
    if body.provider == "openai_compatible" and not body.base_url:
        raise bad_request("A base URL is required for an OpenAI-compatible endpoint")
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise bad_request("Base URL must start with http:// or https://")
    c = ProviderCredential(workspace_id=parse_uuid(workspace_id), provider=body.provider, name=body.name,
                           encrypted_value=encrypt_secret(body.value) if body.value else None,
                           hint=(body.value[-4:] if body.value and len(body.value) >= 8 else ""), base_url=body.base_url,
                           created_by=user.id)
    db.add(c)
    await db.flush()
    await audit(db, "credential_created", user_id=user.id, workspace_id=c.workspace_id, target_type="credential", target_id=c.id,
                data={"provider": body.provider, "name": body.name})
    await db.commit()
    return cred_out(c)


async def _load_cred(db, user, credential_id, role="viewer") -> ProviderCredential:
    c = await db.get(ProviderCredential, parse_uuid(credential_id, "Credential"))
    if c is None:
        raise not_found("Credential")
    await membership(db, user, c.workspace_id, role)
    return c


@router.patch("/credentials/{credential_id}")
async def update_credential(credential_id: str, body: CredentialPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _load_cred(db, user, credential_id, "admin")
    if body.name is not None:
        c.name = body.name
    if body.value:
        c.encrypted_value = encrypt_secret(body.value)
        c.hint = body.value[-4:] if len(body.value) >= 8 else ""
    if body.base_url is not None:
        c.base_url = body.base_url or None
    await audit(db, "credential_updated", user_id=user.id, workspace_id=c.workspace_id, target_id=c.id, data={"rotated": bool(body.value)})
    await db.commit()
    return cred_out(c)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _load_cred(db, user, credential_id, "admin")
    await audit(db, "credential_deleted", user_id=user.id, workspace_id=c.workspace_id, target_id=c.id, data={"name": c.name})
    await db.delete(c)
    await db.commit()


@router.post("/credentials/{credential_id}/test")
async def test_credential(credential_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _load_cred(db, user, credential_id, "editor")
    if c.provider not in provider_classes():
        return {"ok": True, "message": "Stored. This secret is not an LLM provider key, so it cannot be tested automatically."}
    prov = get_provider(c.provider, decrypt_secret(c.encrypted_value) if c.encrypted_value else None, c.base_url)
    try:
        models = await asyncio.wait_for(prov.list_models(), timeout=10)
        return {"ok": True, "message": f"Connected. {len(models)} models available.", "model_count": len(models)}
    except (ProviderError, Exception) as e:
        return {"ok": False, "message": redact_text(str(e))[:300]}


# ------------------------------------------------------------------ pricing (updateable without deployment)
@router.get("/pricing")
async def list_pricing(provider: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = select(ModelPricing)
    if provider:
        q = q.where(ModelPricing.provider == provider)
    rows = (await db.execute(q.order_by(ModelPricing.provider, ModelPricing.model))).scalars().all()
    return [dump(r, "id", "provider", "model", "display_name", "context_window", "input_per_mtok", "output_per_mtok",
                 "cached_input_per_mtok", "capabilities", "active", "updated_at") for r in rows]


@router.put("/pricing")
async def upsert_pricing(rows: list[PricingRow], user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not user.is_admin:
        raise forbidden("Only installation administrators can change model pricing")
    for row in rows:
        existing = (await db.execute(select(ModelPricing).where(ModelPricing.provider == row.provider,
                                                                ModelPricing.model == row.model))).scalar_one_or_none()
        if existing:
            for k, v in row.model_dump().items():
                setattr(existing, k, v)
        else:
            db.add(ModelPricing(**row.model_dump()))
    await audit(db, "pricing_updated", user_id=user.id, data={"rows": len(rows)})
    await db.commit()
    return {"updated": len(rows)}


@router.get("/settings/limits")
async def server_limits(user: User = Depends(current_user)):
    s = get_settings()
    return {"ceilings": {"max_runtime_seconds": s.ceiling_runtime_seconds, "max_llm_calls": s.ceiling_llm_calls,
                         "max_tool_calls": s.ceiling_tool_calls, "max_loop_iterations": s.ceiling_loop_iterations,
                         "max_retries_per_node": s.ceiling_retries, "max_parallel_nodes": s.ceiling_parallel_nodes,
                         "max_cost": s.ceiling_cost_usd, "max_total_tokens": s.ceiling_tokens},
            "search_provider": s.search_provider, "embedding_provider": s.embedding_provider,
            "test_provider_enabled": s.enable_test_provider, "max_upload_mb": s.max_upload_mb}
