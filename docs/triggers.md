# Triggers

Project → **Triggers** (`POST /api/v1/projects/{id}/triggers {"workflow_id", "kind", "name", "config"}`). Triggers run
the latest **published** version of the workflow.

| Kind | Config | Fires |
|---|---|---|
| `webhook` | `auth`: `hmac` (default) or `token` | `POST /hooks/{public_id}` (also `/v1/hooks/...`). HMAC: headers `X-Isocline-Timestamp` and `X-Isocline-Signature: sha256=<hex HMAC(secret, "{ts}.{body}")>`, 5-minute window, each signature accepted once. The secret is shown once at creation. |
| `schedule` | `cron` (5 fields or presets), `timezone` (IANA) | from PostgreSQL by the beat scheduler, exactly once per slot; `GET /api/v1/schedules/preview` shows next times |
| `event` | `event_name` | `POST /api/v1/workspaces/{id}/events {"name", "correlation_key", "payload"}` (also resumes matching `wait_event` nodes) |
| `file` | `knowledge_base_id` (optional filter) | when a document is uploaded to the project (payload: `file`, `filename`, `mime`) |

Verified live: a signed webhook started a run (202); replaying the same signature and a bad signature were rejected;
a `* * * * *` schedule fired from beat.
