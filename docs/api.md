# REST API

OpenAPI: `GET /api/openapi.json`; Swagger UI: `/api/docs`. Errors: `{"error": {"code", "message", "details",
"request_id"}}`; every response has `X-Request-ID`.

**Auth.** Browser: session cookie + `X-CSRF-Token` header on writes. Automation: `Authorization: Bearer isc_pat_...`
(personal access tokens; no CSRF needed). Rate limits apply per session/IP.

| Area | Endpoints (prefix `/api/v1`) |
|---|---|
| Meta | `GET /meta` (version, modules, sign-up policy; public) |
| Auth | `POST /auth/register`, `/auth/login`, `/auth/logout`, `GET /auth/me`, `POST /tokens` |
| Workspaces/projects | `GET /workspaces`, `GET/POST /workspaces/{id}/projects`, `GET/PATCH/DELETE /projects/{id}` |
| Workflows | `GET/POST /projects/{id}/workflows`, `GET/PUT/DELETE /workflows/{id}`, `POST /workflows/{id}/validate`, `/plan`, `/publish`, `/run`, `GET /workflows/{id}/export`, `POST /projects/{id}/workflows/import`, `GET /workflows/{id}/versions` |
| Runs | `GET /runs/{id}`, `/runs/{id}/nodes`, `/runs/{id}/events` (SSE), `/runs/{id}/events.json`, `/runs/{id}/harness`, `/runs/{id}/lineage`, `POST /runs/{id}/cancel`, `/replay`, `/resume`, `/compensate`, `GET /runs/compare/{a}/{b}` |
| Nodes | `POST /workflows/{id}/nodes/{node_id}/playground` (run one node with supplied input and mocked upstream) |
| Approvals | `GET /workspaces/{id}/approvals`, `GET /runs/{id}/approvals`, `POST /approvals/{id}/decide` |
| Artifacts | `GET /projects/{id}/artifacts`, `GET /artifacts/{id}`, `/preview`, `/download`, `DELETE /artifacts/{id}` |
| Triggers & events | `GET/POST /projects/{id}/triggers`, `PUT/DELETE /triggers/{id}`, `POST /workspaces/{id}/events`; public `POST /hooks/{public_id}`, `POST /v1/callbacks/{run_id}/{node_id}/{token}` |
| Knowledge | `GET/POST /projects/{id}/knowledge-bases`, `POST /knowledge-bases/{id}/documents` (multipart), `POST /documents/{id}/reprocess`, `POST /knowledge-bases/{id}/search` |
| Models & keys | `GET /providers`, `/providers/{id}/models`, `GET/POST /workspaces/{id}/credentials`, `GET/PUT /pricing`, `GET /settings/limits` |
| MCP & policies | `GET/POST /workspaces/{id}/mcp`, `POST /mcp/{id}/sync`, `GET/POST /workspaces/{id}/policies` |

Example:

```bash
T=isc_pat_...; B=http://localhost:8000/api/v1
curl -s -X POST $B/workflows/<id>/run -H "Authorization: Bearer $T" -H 'content-type: application/json' \
  -d '{"input": {"company": "Acme Corp"}}'          # → {"run_id": "...", "status": "queued"}
curl -s $B/runs/<run_id> -H "Authorization: Bearer $T"
```

Optional-module endpoints are mounted only when the module is enabled.
