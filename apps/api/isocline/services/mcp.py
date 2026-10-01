"""Minimal MCP client (Model Context Protocol, streamable HTTP transport).

Only HTTP(S) endpoints are supported. stdio servers would execute arbitrary commands on the Isocline host and
are deliberately not offered. Endpoints are SSRF-checked unless the operator allows private hosts.
Connecting a server grants nothing by itself: each agent must list `mcp:<server>/<tool>` explicitly, the tool must
be on the server's allowlist, and every call still passes the policy engine, HITL, audit and rate limits."""
from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

from isocline.core.config import get_settings
from isocline.tools.ssrf import check_url

PROTOCOL_VERSION = "2025-06-18"
_ids = itertools.count(1)


class McpError(Exception):
    pass


def _parse(resp: httpx.Response) -> dict:
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        last = None
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if "result" in msg or "error" in msg:
                    last = msg
        if last is None:
            raise McpError("MCP server returned no JSON-RPC response")
        return last
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        raise McpError(f"MCP server returned invalid JSON ({resp.status_code})") from e


class McpClient:
    def __init__(self, endpoint: str, token: str | None = None, timeout: float = 30):
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict | None = None, notify: bool = False) -> Any:
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            body["id"] = next(_ids)
        r = await client.post(self.endpoint, headers=self._headers(), json=body)
        if r.headers.get("mcp-session-id"):
            self.session_id = r.headers["mcp-session-id"]
        if notify:
            return None
        if r.status_code >= 400:
            raise McpError(f"MCP {method} failed: HTTP {r.status_code}")
        msg = _parse(r)
        if "error" in msg:
            raise McpError(f"MCP {method} error: {msg['error'].get('message')}")
        return msg.get("result")

    async def _open(self, client: httpx.AsyncClient) -> None:
        if not get_settings().allow_private_network_hosts:
            await check_url(self.endpoint)
        await self._rpc(client, "initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                               "clientInfo": {"name": "isocline", "version": "2.0"}})
        await self._rpc(client, "notifications/initialized", notify=True)

    async def list_tools(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as c:
            await self._open(c)
            tools, cursor = [], None
            for _ in range(20):
                res = await self._rpc(c, "tools/list", {"cursor": cursor} if cursor else {})
                tools += res.get("tools", [])
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as c:
            await self._open(c)
            res = await self._rpc(c, "tools/call", {"name": name, "arguments": arguments})
            content = res.get("content") or []
            texts = [x.get("text") for x in content if x.get("type") == "text"]
            out = {"content": "\n".join(t for t in texts if t), "is_error": bool(res.get("isError"))}
            if res.get("structuredContent") is not None:
                out["structured"] = res["structuredContent"]
            if out["is_error"]:
                raise McpError(out["content"] or "MCP tool reported an error")
            return out
