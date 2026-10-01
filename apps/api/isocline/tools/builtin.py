"""Built-in tools: web search, HTTP, Python sandbox, file reader, JSON processor, vector search."""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from isocline.core.config import get_settings
from isocline.engine.expressions import Scope, compare, resolve_value

from .base import Tool, ToolError
from .calculator import CalculatorTool
from .ssrf import check_url, pinned_request  # noqa: F401

MAX_HTTP_BYTES = 1_000_000


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the public web. Returns titles, URLs and snippets. Cite URLs you rely on."
    input_schema = {"type": "object", "properties": {
        "query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 10}},
        "required": ["query"]}
    permissions = ["network"]

    async def execute(self, args, ctx):
        q = str(args.get("query", "")).strip()
        if not q:
            raise ToolError("query is required")
        n = int(args.get("max_results") or 5)
        s = get_settings()
        prov = s.search_provider
        async with httpx.AsyncClient(timeout=20) as c:
            if prov == "tavily":
                key = await ctx.get_secret("tavily")
                if not key:
                    raise ToolError("Web Search credential missing (add a Tavily key under Secrets)")
                r = await c.post("https://api.tavily.com/search", json={"api_key": key, "query": q, "max_results": n})
                r.raise_for_status()
                results = [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")[:500]}
                           for x in r.json().get("results", [])]
            elif prov == "brave":
                key = await ctx.get_secret("brave")
                if not key:
                    raise ToolError("Web Search credential missing (add a Brave Search key under Secrets)")
                r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": n},
                                headers={"X-Subscription-Token": key, "Accept": "application/json"})
                r.raise_for_status()
                results = [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("description", "")}
                           for x in (r.json().get("web") or {}).get("results", [])]
            else:
                r = await c.get(f"{s.searxng_url.rstrip('/')}/search", params={"q": q, "format": "json"})
                r.raise_for_status()
                results = [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
                           for x in r.json().get("results", [])]
        return {"query": q, "results": results[:n]}


class HttpRequestTool(Tool):
    name = "http_request"
    description = "Call an HTTP API. Private networks, localhost and cloud metadata endpoints are blocked."
    input_schema = {"type": "object", "properties": {
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "url": {"type": "string"},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "query": {"type": "object"},
        "body": {}},
        "required": ["url"]}
    permissions = ["network"]

    async def execute(self, args, ctx):
        method = str(args.get("method") or "GET").upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ToolError(f"Unsupported method {method}")
        url = str(args.get("url") or "")
        headers = {str(k): str(v) for k, v in (args.get("headers") or {}).items()}
        # {{secret:NAME}} placeholders are resolved server-side and never shown to the model.
        for k, v in list(headers.items()):
            if v.startswith("{{secret:") and v.endswith("}}"):
                val = await ctx.get_secret(v[9:-2].strip())
                if val is None:
                    raise ToolError(f"Secret '{v[9:-2]}' not found")
                ctx.secret_values.append(val)
                headers[k] = val
        body = args.get("body")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
            for _ in range(5):  # follow redirects manually so every hop is SSRF-checked
                target, pin_headers, ext = await pinned_request(url)  # connect to the checked address (no DNS rebinding)
                kw: dict[str, Any] = {"headers": {**headers, **pin_headers}, "params": args.get("query") or None,
                                      "extensions": ext}
                if body is not None and method != "GET":
                    kw["json" if not isinstance(body, str) else "content"] = body
                async with c.stream(method, target, **kw) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = str(httpx.URL(url).join(r.headers["location"]))
                        continue
                    chunks, total = [], 0
                    async for chunk in r.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_HTTP_BYTES:
                            raise ToolError("Response exceeds 1 MB limit")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    text = raw.decode(r.encoding or "utf-8", errors="replace")
                    try:
                        data: Any = json.loads(text)
                    except ValueError:
                        data = text[:20000]
                    return {"status": r.status_code, "headers": {k: v for k, v in r.headers.items()
                                                                if k.lower() in ("content-type", "content-length")},
                            "body": data}
        raise ToolError("Too many redirects")


class PythonTool(Tool):
    name = "python"
    description = ("Execute Python 3 code in an isolated sandbox (no network). Print results to stdout. "
                   "Variables passed in `inputs` are available as the dict INPUTS. Files written to ./out are returned.")
    input_schema = {"type": "object", "properties": {"code": {"type": "string"}, "inputs": {"type": "object"}},
                    "required": ["code"]}
    permissions = ["code_execution"]

    async def execute(self, args, ctx):
        s = get_settings()
        code = str(args.get("code") or "")
        if not code.strip():
            raise ToolError("code is required")
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{s.sandbox_url.rstrip('/')}/execute",
                                 headers={"Authorization": f"Bearer {s.sandbox_token}"},
                                 json={"code": code, "inputs": args.get("inputs") or {}, "timeout_seconds": 30})
        except httpx.TransportError as e:
            raise ToolError("Python sandbox is unavailable") from e
        if r.status_code >= 400:
            raise ToolError(f"Sandbox error ({r.status_code}): {r.text[:300]}")
        return r.json()


class FileReaderTool(Tool):
    name = "file_reader"
    description = "Read the text content of an uploaded project document by document_id."
    input_schema = {"type": "object", "properties": {"document_id": {"type": "string"},
                                                      "max_chars": {"type": "integer"}}, "required": ["document_id"]}
    permissions = ["filesystem"]

    async def execute(self, args, ctx):
        from isocline.db.models import Document
        from isocline.services.documents import extract_text
        from isocline.services.storage import storage
        if ctx.open_session is None:
            raise ToolError("File access is unavailable in this context")
        try:
            did = uuid.UUID(str(args.get("document_id")))
        except ValueError as e:
            raise ToolError("Invalid document_id") from e
        async with ctx.open_session() as db:
            doc = await db.get(Document, did)
            if doc is None or str(doc.project_id) != str(ctx.project_id):
                raise ToolError("Document not found in this project")
            data = await storage().get(doc.storage_key)
            text = extract_text("." + doc.filename.rsplit(".", 1)[-1].lower(), data)
        limit = int(args.get("max_chars") or 20000)
        return {"document_id": str(did), "filename": doc.filename, "text": text[:limit], "truncated": len(text) > limit}


class JsonProcessorTool(Tool):
    name = "json_processor"
    description = ("Process JSON: operation 'get' (path like a.b[0]), 'pick' (keys), 'filter' (list items where "
                   "field op value), 'parse' (string to JSON), 'count', 'sort' (by field).")
    input_schema = {"type": "object", "properties": {
        "operation": {"type": "string", "enum": ["get", "pick", "filter", "parse", "count", "sort"]},
        "data": {}, "path": {"type": "string"}, "keys": {"type": "array", "items": {"type": "string"}},
        "field": {"type": "string"}, "operator": {"type": "string"}, "value": {}, "descending": {"type": "boolean"}},
        "required": ["operation", "data"]}

    async def execute(self, args, ctx):
        op, data = args.get("operation"), args.get("data")
        if isinstance(data, str) and op != "parse":
            try:
                data = json.loads(data)
            except ValueError:
                pass
        if op == "parse":
            try:
                return {"result": json.loads(data) if isinstance(data, str) else data}
            except ValueError as e:
                raise ToolError(f"Invalid JSON: {e}") from e
        if op == "get":
            return {"result": resolve_value("{{d" + ("." + args["path"] if args.get("path") and not str(args["path"]).startswith("[") else args.get("path", "")) + "}}",
                                            Scope({}, {}, variables={}).child(d=data))}
        if op == "pick":
            if not isinstance(data, dict):
                raise ToolError("pick requires an object")
            return {"result": {k: data.get(k) for k in args.get("keys") or []}}
        if op == "count":
            return {"result": len(data) if hasattr(data, "__len__") else 0}
        if not isinstance(data, list):
            raise ToolError(f"{op} requires a list")
        field = args.get("field") or ""
        get = (lambda x: x.get(field) if isinstance(x, dict) else None) if field else (lambda x: x)
        if op == "filter":
            return {"result": [x for x in data if compare(get(x), args.get("operator") or "==", args.get("value"))]}
        if op == "sort":
            return {"result": sorted(data, key=lambda x: (get(x) is None, get(x)), reverse=bool(args.get("descending")))}
        raise ToolError(f"Unknown operation {op}")


class VectorSearchTool(Tool):
    name = "vector_search"
    description = "Search the project knowledge base for passages relevant to a query. Returns passages with sources."
    input_schema = {"type": "object", "properties": {"query": {"type": "string"},
                                                      "top_k": {"type": "integer", "minimum": 1, "maximum": 20}},
                    "required": ["query"]}
    permissions = ["knowledge"]

    async def execute(self, args, ctx):
        from isocline.services.knowledge import retrieve
        if not ctx.knowledge_base_ids:
            raise ToolError("No knowledge base is attached to this agent")
        if ctx.open_session is None:
            raise ToolError("Knowledge search is unavailable in this context")
        async with ctx.open_session() as db:
            res = await retrieve(db, ctx.knowledge_base_ids, str(args.get("query", "")), int(args.get("top_k") or 5))
        return {"query": args.get("query"), "results": res}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    WebSearchTool(), HttpRequestTool(), PythonTool(), CalculatorTool(), FileReaderTool(), JsonProcessorTool(), VectorSearchTool(),
]}

# Standalone tool node type -> tool name
NODE_TOOL = {"tool_web_search": "web_search", "tool_http": "http_request", "tool_python": "python",
             "tool_calculator": "calculator", "tool_file_reader": "file_reader", "tool_json": "json_processor",
             "tool_vector_search": "vector_search"}
