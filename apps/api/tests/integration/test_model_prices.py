"""Model list and pricing: live prices from the feed, only usable + priced models listed, admin prices respected,
AUTO routing limited to the curated catalog, and UTC timestamps on SQLite."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import respx
from sqlalchemy import select

from isocline.db.models import ModelPricing
from isocline.services import model_prices
from tests.conftest import signup

FEED = {
    "sample_spec": {"mode": "chat"},
    "gpt-5.6-terra": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 2e-06,
                      "output_cost_per_token": 1.2e-05, "cache_read_input_token_cost": 2e-07, "max_input_tokens": 922000,
                      "supports_function_calling": True, "supports_response_schema": True, "supports_vision": True},
    "gpt-4o": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 2.5e-06,
               "output_cost_per_token": 1e-05, "max_input_tokens": 128000},
    "text-embedding-3-small": {"litellm_provider": "openai", "mode": "embedding", "input_cost_per_token": 2e-08,
                               "output_cost_per_token": 0},
    "openai/gpt-4o": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 1, "output_cost_per_token": 1},
    "claude-sonnet-5-5": {"litellm_provider": "anthropic", "mode": "chat", "input_cost_per_token": 2e-06,
                          "output_cost_per_token": 1e-05, "max_input_tokens": 1000000},
    "gemini/gemini-2.5-pro": {"litellm_provider": "gemini", "mode": "chat", "input_cost_per_token": 1.25e-06,
                              "output_cost_per_token": 1e-05},
    "azure/gpt-5.6-terra": {"litellm_provider": "azure", "mode": "chat", "input_cost_per_token": 1, "output_cost_per_token": 1},
}


def test_parse_keeps_chat_models_of_supported_providers_with_prices():
    rows = {(r["provider"], r["model"]): r for r in model_prices.parse(FEED)}
    assert set(rows) == {("openai", "gpt-5.6-terra"), ("openai", "gpt-4o"), ("anthropic", "claude-sonnet-5-5"),
                         ("google", "gemini-2.5-pro")}
    t = rows[("openai", "gpt-5.6-terra")]
    assert (t["input_per_mtok"], t["output_per_mtok"], t["cached_input_per_mtok"]) == (2.0, 12.0, 0.2)
    assert t["context_window"] == 922000 and t["capabilities"]["tool_calling"] and t["capabilities"]["structured_output"]


async def test_refresh_adds_new_models_updates_catalog_and_never_touches_admin_prices(env):
    from isocline.db.seed import seed
    db = env["db"]
    await seed(db)  # the shipped catalog, as on a real installation
    admin = (await db.execute(select(ModelPricing).where(ModelPricing.provider == "anthropic"))).scalars().first()
    db.add(ModelPricing(provider="anthropic", model="claude-sonnet-5-5", input_per_mtok=9.0, output_per_mtok=9.0,
                        source="admin"))
    await db.commit()
    with respx.mock:
        respx.get("https://prices.test/feed.json").mock(return_value=httpx.Response(200, json={**FEED, **{f"x{i}": {} for i in range(60)}}))
        st = await model_prices.refresh(db, "https://prices.test/feed.json")
    assert st["error"] is None and st["models"] == 4
    rows = {(r.provider, r.model): r for r in (await db.execute(select(ModelPricing))).scalars()}
    terra = rows[("openai", "gpt-5.6-terra")]
    assert terra.source == "feed" and (terra.input_per_mtok, terra.output_per_mtok) == (2.0, 12.0)
    gpt4o = rows[("openai", "gpt-4o")]  # shipped catalog row: price updated, extra hints kept, still "catalog"
    assert gpt4o.source == "catalog" and gpt4o.input_per_mtok == 2.5 and "quality_tier" in gpt4o.capabilities
    sonnet = rows[("anthropic", "claude-sonnet-5-5")]
    assert sonnet.source == "admin" and sonnet.input_per_mtok == 9.0  # an administrator's price wins
    assert admin is None or rows[(admin.provider, admin.model)]


async def test_refresh_failure_keeps_previous_prices(env):
    with respx.mock:
        respx.get("https://prices.test/down.json").mock(return_value=httpx.Response(503))
        st = await model_prices.refresh(env["db"], "https://prices.test/down.json")
    assert st["error"]


async def test_model_list_shows_only_available_priced_models(app_env, monkeypatch):
    api = app_env["new"]()
    await signup(api)
    async with __import__("isocline.db.session", fromlist=["sessionmaker"]).sessionmaker()() as db:
        await model_prices.apply(db, model_prices.parse(FEED))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="test").pass_through()
        mock.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(200, json={"data": [
            {"id": "gpt-5.6-terra"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "gpt-4o"}]}))
        ws = (await api.get("/api/v1/workspaces")).json()
        ws_id = (ws if isinstance(ws, list) else ws.get("items") or ws.get("workspaces"))[0]["id"]
        r = (await api.get(f"/api/v1/providers/openai/models?workspace_id={ws_id}")).json()
    ids = [m["id"] for m in r["models"]]
    assert ids == ["gpt-4o", "gpt-5.6-terra"]  # catalog models the key cannot use are not listed; no embeddings/audio
    terra = next(m for m in r["models"] if m["id"] == "gpt-5.6-terra")
    assert terra["pricing"]["input_per_mtok"] == 2.0 and terra["pricing"]["output_per_mtok"] == 12.0


async def test_model_list_without_a_key_is_empty_with_a_hint(app_env, monkeypatch):
    api = app_env["new"]()
    await signup(api)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ws = (await api.get("/api/v1/workspaces")).json()
    ws_id = (ws if isinstance(ws, list) else ws.get("items") or ws.get("workspaces"))[0]["id"]
    r = (await api.get(f"/api/v1/providers/anthropic/models?workspace_id={ws_id}")).json()
    assert r["models"] == [] and "key" in r["warning"]


def test_auto_routing_ignores_feed_only_models():
    from isocline.engine.router import Candidate, route
    cheap_feed = Candidate("openai", "gpt-3.5-turbo-0301", {"text": True}, 16000,
                           {"input_per_mtok": 0.01, "output_per_mtok": 0.01}, True, curated=False)
    curated = Candidate("openai", "gpt-4o", {"text": True}, 128000, {"input_per_mtok": 2.5, "output_per_mtok": 10}, True)
    d = route([cheap_feed, curated], required=[], est_input_tokens=100, est_output_tokens=100,
              routing={"objective": "cost"}, policy_snapshot=[])
    assert d.model == "gpt-4o"


async def test_timestamps_come_back_as_utc_on_sqlite(env):
    from isocline.db.models import utcnow
    db = env["db"]
    row = ModelPricing(provider="local_test", model="tz-check", input_per_mtok=0, output_per_mtok=0)
    db.add(row)
    await db.commit()
    written = utcnow()
    db.expire_all()
    got = (await db.execute(select(ModelPricing).where(ModelPricing.model == "tz-check"))).scalar_one()
    assert got.updated_at.tzinfo is not None and got.updated_at.utcoffset().total_seconds() == 0
    assert abs((written - got.updated_at).total_seconds()) < 5
    assert datetime.now(timezone.utc) - got.updated_at < __import__("datetime").timedelta(minutes=1)
