"""Current model prices and capabilities from a live feed.

Source: LiteLLM's community-maintained price list (MIT licensed), which tracks the official pricing pages of OpenAI,
Anthropic, Google, OpenRouter and others and is updated as new models ship. Isocline fetches it on start and every
`model_prices_refresh_hours`, and writes the prices into the model_pricing table that cost estimates, budgets,
preflight and the model picker already use. Prices are estimates; the provider's invoice is authoritative.

Ownership of a row (`model_pricing.source`):
  * "catalog": shipped with Isocline (data/model_catalog.json); the feed updates its prices and context window.
  * "feed":    added by the feed.
  * "admin":   set by an administrator through PUT /pricing; never overwritten.

Set ISOCLINE_MODEL_PRICES_URL="" to disable fetching (air-gapped servers); the shipped catalog is used instead.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.config import get_settings
from isocline.core.logging import log
from isocline.db.models import ModelPricing, utcnow

# Isocline provider id -> (LiteLLM provider name, prefix of its keys). Local providers are free and listed separately.
FEED_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("openai", ""),
    "anthropic": ("anthropic", ""),
    "google": ("gemini", "gemini/"),
    "openrouter": ("openrouter", "openrouter/"),
}
FREE_PROVIDERS = {"ollama", "local_test"}  # run on this computer / deterministic test provider: no per-token price
CHAT_MODES = {"chat", "responses"}  # not embeddings, images, audio, moderation, ...

_status: dict = {"updated_at": None, "models": 0, "error": None}


def status() -> dict:
    """When prices were last refreshed, how many models they cover, and the last error (if any)."""
    return dict(_status)


def parse(feed: dict) -> list[dict]:
    """Feed entries -> model_pricing rows for the providers Isocline supports (chat models with a price only)."""
    rows: list[dict] = []
    for key, v in feed.items():
        if not isinstance(v, dict) or v.get("mode") not in CHAT_MODES:
            continue
        for provider, (feed_provider, prefix) in FEED_PROVIDERS.items():
            if v.get("litellm_provider") != feed_provider:
                continue
            if prefix and not key.startswith(prefix):
                continue
            model = key[len(prefix):]
            if not prefix and "/" in model:  # e.g. "openai/..." aliases or regional variants: not an API model id
                continue
            inp, out = v.get("input_cost_per_token"), v.get("output_cost_per_token")
            if inp is None or out is None:
                continue
            cached = v.get("cache_read_input_token_cost")
            caps = {"text": True}
            for flag, cap in (("supports_function_calling", "tool_calling"), ("supports_vision", "vision"),
                              ("supports_response_schema", "structured_output"), ("supports_reasoning", "reasoning")):
                if flag in v:
                    caps[cap] = bool(v[flag])
            rows.append({
                "provider": provider, "model": model,
                "context_window": v.get("max_input_tokens") or v.get("max_tokens"),
                "input_per_mtok": round(float(inp) * 1_000_000, 6),
                "output_per_mtok": round(float(out) * 1_000_000, 6),
                "cached_input_per_mtok": round(float(cached) * 1_000_000, 6) if cached is not None else None,
                "capabilities": caps,
            })
    return rows


async def fetch(url: str) -> dict:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": "Isocline"})
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict) or len(data) < 50:
        raise ValueError("the price list looks empty or malformed")
    return data


async def apply(db: AsyncSession, rows: list[dict]) -> int:
    """Upserts feed rows; administrator-owned rows are never changed. Returns the number of rows written."""
    existing = {(r.provider, r.model): r for r in (await db.execute(select(ModelPricing))).scalars()}
    n = 0
    for row in rows:
        cur = existing.get((row["provider"], row["model"]))
        if cur is None:
            db.add(ModelPricing(**row, display_name=row["model"], source="feed", active=True))
            n += 1
        elif (cur.source or "catalog") != "admin":
            cur.input_per_mtok = row["input_per_mtok"]
            cur.output_per_mtok = row["output_per_mtok"]
            cur.cached_input_per_mtok = row["cached_input_per_mtok"]
            cur.context_window = row["context_window"] or cur.context_window
            # keep the catalog's extra hints (quality tier, latency, ...); the feed decides the yes/no capabilities
            cur.capabilities = {**(cur.capabilities or {}), **row["capabilities"]}
            if cur.source != "catalog":
                cur.source = "feed"
            n += 1
    await db.commit()
    return n


async def refresh(db: AsyncSession, url: str | None = None) -> dict:
    url = get_settings().model_prices_url if url is None else url
    if not url:
        return status()
    try:
        rows = parse(await fetch(url))
        n = await apply(db, rows)
        _status.update(updated_at=utcnow().isoformat(), models=len(rows), error=None)
        log.info("model_prices_refreshed", models=len(rows), written=n)
    except Exception as e:  # keep the previous prices; try again at the next interval
        _status.update(error=str(e)[:300])
        log.warning("model_prices_refresh_failed", error=str(e)[:300])
    return status()


async def refresh_loop() -> None:
    """On start, then every model_prices_refresh_hours. Started from the API's lifespan."""
    from isocline.db import session as dbs
    await asyncio.sleep(3)  # let start-up finish first
    while True:
        async with dbs.sessionmaker()() as db:
            await refresh(db)
        await asyncio.sleep(max(1, get_settings().model_prices_refresh_hours) * 3600)


def last_updated() -> datetime | None:
    v = _status.get("updated_at")
    return datetime.fromisoformat(v) if v else None
