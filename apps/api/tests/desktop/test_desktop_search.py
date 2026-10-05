"""Desktop web search: "auto" picks a configured key, otherwise the bundled local search (SearXNG-compatible JSON)."""
from __future__ import annotations

import httpx
import pytest
import respx

from isocline.tools.base import ToolContext
from isocline.tools.builtin import ToolError, WebSearchTool

LOCAL = "http://127.0.0.1:47555"


def ctx(secrets: dict[str, str] | None = None) -> ToolContext:
    async def get_secret(name: str):
        return (secrets or {}).get(name)
    return ToolContext(workspace_id="w", project_id="p", run_id=None, get_secret=get_secret)


@pytest.fixture
def auto(monkeypatch):
    from isocline.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "search_provider", "auto")
    monkeypatch.setattr(s, "searxng_url", LOCAL)
    return s


@respx.mock
async def test_auto_uses_local_search_without_a_key(auto):
    respx.get(f"{LOCAL}/search").mock(return_value=httpx.Response(200, json={
        "query": "python", "unresponsive_engines": [["brave", "timeout"]],
        "results": [{"title": "Python", "url": "https://www.python.org/", "content": "The official home", "engine": "duckduckgo"}]}))
    out = await WebSearchTool().execute({"query": "python"}, ctx())
    text = str(out)
    assert "https://www.python.org/" in text and "The official home" in text


@respx.mock
async def test_auto_prefers_a_configured_tavily_key(auto):
    local = respx.get(f"{LOCAL}/search")
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(200, json={
        "results": [{"title": "T", "url": "https://t.example/", "content": "from tavily"}]}))
    out = await WebSearchTool().execute({"query": "python"}, ctx({"tavily": "tvly-x"}))
    assert "from tavily" in str(out) and not local.called


@respx.mock
async def test_all_engines_failing_is_an_error_not_empty_results(auto):
    respx.get(f"{LOCAL}/search").mock(return_value=httpx.Response(200, json={
        "query": "q", "results": [], "unresponsive_engines": [["duckduckgo", "AccessDenied"], ["brave", "timeout"]]}))
    with pytest.raises(ToolError, match="no search engine responded"):
        await WebSearchTool().execute({"query": "q"}, ctx())


@respx.mock
async def test_local_search_not_running_is_explained(auto):
    respx.get(f"{LOCAL}/search").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="search service is not running"):
        await WebSearchTool().execute({"query": "q"}, ctx())


async def test_preflight_does_not_require_a_key_in_auto_mode(env, auto, monkeypatch):
    from isocline.schemas.workflow import WorkflowGraph
    from isocline.services.validation import validate_environment
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    g = WorkflowGraph.model_validate({"nodes": [{"id": "s", "key": "search", "type": "tool_web_search",
                                                 "config": {"arguments": {"query": "x"}}}], "edges": []})
    issues = await validate_environment(env["db"], g, env["workspace"].id, env["project"].id)
    assert "search_credential_missing" not in {i.code for i in issues}
