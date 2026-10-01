"""SSRF controls for agent-initiated HTTP (HTTP tool, MCP endpoints, provider base URLs)."""
from __future__ import annotations

import socket

import httpx
import pytest
import respx

from isocline.tools.base import ToolContext, ToolError
from isocline.tools.builtin import TOOLS
from isocline.tools.ssrf import check_url, pinned_request

BLOCKED = [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",  # AWS/GCP/Azure metadata
    "http://[fd00:ec2::254]/latest/meta-data/", "http://100.100.100.200/latest/meta-data/",  # AWS IPv6, Alibaba
    "http://metadata.google.internal/computeMetadata/v1/", "http://metadata/", "http://instance-data/",
    "http://localhost:8000/api/v1/", "http://api.localhost/", "http://127.0.0.1:6379/", "http://127.1/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[::ffff:169.254.169.254]/", "http://0.0.0.0/",
    "http://10.0.0.5/", "http://172.16.0.1/", "http://192.168.1.1/", "http://100.64.0.1/", "http://169.254.1.1/",
    "http://2130706433/", "http://0x7f000001/", "http://017700000001/",  # 127.0.0.1 in decimal / hex / octal
    "http://postgres.internal/", "file:///etc/passwd", "gopher://127.0.0.1:6379/_FLUSHALL", "ftp://example.com/",
]


@pytest.mark.parametrize("url", BLOCKED)
async def test_internal_targets_are_blocked(url):
    with pytest.raises(ToolError):
        await check_url(url)


async def test_name_resolving_to_private_address_is_blocked(monkeypatch):
    async def fake(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", lambda self, *a, **k: fake(*a, **k))
    with pytest.raises(ToolError, match="private or internal"):
        await check_url("http://innocent-looking.example.com/")


async def test_any_private_answer_blocks_even_with_public_ones(monkeypatch):
    async def fake(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", lambda self, *a, **k: fake(*a, **k))
    with pytest.raises(ToolError):
        await check_url("http://mixed.example.com/")


async def test_dns_rebinding_is_defeated_by_pinning(monkeypatch):
    """The resolver answers public first, then loopback. The request must go to the checked (public) address."""
    answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1"])

    async def fake(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), port))]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", lambda self, *a, **k: fake(*a, **k))
    url, headers, ext = await pinned_request("https://rebind.example.com:8443/x?y=1")
    assert url == "https://93.184.216.34:8443/x?y=1"
    assert headers == {"Host": "rebind.example.com:8443"} and ext == {"sni_hostname": "rebind.example.com"}


def _ctx():
    async def no_secret(_):
        return None
    return ToolContext(workspace_id="w", project_id="p", run_id="r", get_secret=no_secret, knowledge_base_ids=[], open_session=None)


async def test_http_tool_connects_to_checked_ip_with_original_host(monkeypatch):
    async def fake(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", lambda self, *a, **k: fake(*a, **k))
    with respx.mock(assert_all_called=True) as m:
        route = m.get("http://93.184.216.34/data").mock(return_value=httpx.Response(200, json={"ok": True}))
        out = await TOOLS["http_request"].execute({"url": "http://api.example.com/data"}, _ctx())
    assert out["status"] == 200 and out["body"] == {"ok": True}
    assert route.calls.last.request.headers["host"] == "api.example.com"


async def test_redirect_to_metadata_is_blocked(monkeypatch):
    async def fake(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", lambda self, *a, **k: fake(*a, **k))
    with respx.mock(assert_all_called=False) as m:
        m.get("http://93.184.216.34/go").mock(return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}))
        meta = m.get(url__startswith="http://169.254.169.254").mock(return_value=httpx.Response(200, text="SECRET"))
        with pytest.raises(ToolError):
            await TOOLS["http_request"].execute({"url": "http://evil.example.com/go"}, _ctx())
    assert not meta.called


async def test_administrator_allowlist(monkeypatch):
    from isocline.core.config import get_settings
    monkeypatch.setattr(get_settings(), "allow_private_network_hosts", ["ollama.lan"])
    assert await check_url("http://ollama.lan:11434/api/tags") == "ollama.lan"
    with pytest.raises(ToolError):
        await check_url("http://169.254.169.254/")  # the allowlist is per host, never a global off switch
