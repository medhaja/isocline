# MCP

Isocline is an MCP client for **streamable-HTTP** servers.

1. **Integrations → Add server** (or `POST /api/v1/workspaces/{id}/mcp` `{"name": "crm", "endpoint":
   "https://mcp.example.com/mcp", "allowed_tools": ["lookup_account"], "credential_id": ...}`). The endpoint passes the
   SSRF guard; private hosts need `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS`. A bearer token can come from a stored credential.
2. **Sync** (`POST /api/v1/mcp/{id}/sync`) lists the server's tools. Only tools on the server's **allowlist** can ever be
   called.
3. Grant tools to an agent: `"tools": ["mcp:crm/lookup_account"]`. Validation fails if the server or tool isn't allowed.

Each call goes through policies, approvals, the per-server rate limit and the tool budget, and is recorded like any tool
call. Tool annotations from the server (e.g. read-only hints) inform side-effect classification.

`examples/07-mcp` ships a small server built with the official MCP Python SDK; it was verified end to end (register,
sync, allowlist, agent tool call). Limitations: no stdio transport, no OAuth; the client checks but does not DNS-pin the endpoint.
