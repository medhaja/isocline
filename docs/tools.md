# Tools

Built-in tools (`apps/api/isocline/tools/builtin.py`). Agents use them by name in `tools`; tool nodes call them
directly (`tool_<name>`, except `tool_http` → `http_request` and `tool_vector_search` → `vector_search`).

| Tool | Does | Notes |
|---|---|---|
| `web_search` | web search | provider: SearXNG (profile `search`), Tavily or Brave (`ISOCLINE_SEARCH_PROVIDER`) |
| `http_request` | `GET/POST/PUT/PATCH/DELETE` with headers, query, JSON or text body | SSRF-protected + DNS-pinned, 1 MB responses, `{{secret:name}}` headers ([security](security.md#http-tool-and-ssrf)) |
| `python` | run code in the [sandbox](sandbox.md) with `INPUTS`; files in `out/` become artifacts | no network |
| `calculator` | arithmetic expressions | safe parser, no `eval` |
| `file_reader` | read an uploaded document or artifact as text | |
| `json_processor` | query / reshape JSON | |
| `vector_search` | search the node's knowledge bases | [knowledge](knowledge.md) |
| `mcp:<server>/<tool>` | a tool on a registered MCP server | [MCP](mcp.md) |

Every tool call passes the policy engine (allow / deny / require approval), counts toward `max_tool_calls`, and is
recorded with inputs, outputs and timing (secrets redacted). Adding a tool: [contributing/adding-a-tool.md](contributing/adding-a-tool.md).
