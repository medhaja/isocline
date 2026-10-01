# Human in the loop

The **Human approval** node pauses the run until someone decides. Config: `title`, `instructions`, `content` (template
shown to the reviewer; default the upstream output), `allow_edit` (reviewer may edit what flows on), `max_wait_seconds`
and `timeout_action` (`edge` → follow the `timeout` edge, `fail`, `continue`). Outgoing edges use the handles
`approved`, `rejected` and `timeout`.

Decide in the UI (**Approvals**, or the run page), via `POST /api/v1/approvals/{id}/decide {"decision": "approved" |
"rejected", "edited_content", "comment"}`, or the SDK (`client.approvals.resolve`). Decisions are audited.

While waiting the run is `waiting` and **holds no worker**; restarts of any service don't affect it (verified: API,
worker and Redis restarted mid-wait; approved afterwards; run completed; 0 active worker tasks while waiting).
Policies can also require approval for specific tool calls or whole runs ([Policies] page); a node paused for a
tool-call approval re-runs from its start once approved.

Other durable waits: **timer** (`duration_seconds` or `until`), **callback** (`wait_webhook`: the run exposes a signed
callback URL `{{run.callbacks.<node_key>}}`; the first delivery wins, duplicates are ignored), **event** (`wait_event`:
`event_name` + optional `correlation`; publish with `POST /api/v1/workspaces/{id}/events`). All support
`max_wait_seconds` + `timeout_action`.
