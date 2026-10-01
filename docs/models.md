# Models

An agent's `model` is `{"provider": "<id>", "model": "<name>"}` plus optional `credential_id` (a specific stored key);
`params` (temperature, max_tokens, top_p, reasoning_effort, ...) are filtered to what the model supports and ignored
ones are reported in the trace. `fallbacks` lists models to try when the primary fails (used by recovery rules).
`provider: "auto"` lets the router pick a configured model that satisfies the node's capabilities and policies.

**Model catalog & pricing** (Keys & secrets → Model pricing, `/api/v1/pricing`): seeded from
`apps/api/isocline/data/model_catalog.json`; prices and capability flags are estimates you can edit (admins). Costs
shown on runs are estimates computed from reported token usage and these prices (`cost_is_estimate`).

**Structured output:** set `output_schema` (JSON Schema); providers with native support use it, others are prompted and
parsed; invalid JSON is repaired or retried per the recovery rules.

**Workflow memory:** with `settings.workflow_memory_enabled`, an agent with `memory.write_workflow_memory` stores its
output under `memory_key`; later runs read it as `{{memory.<key>}}`. Inspect/clear: `/api/v1/workflows/{id}/memory`.

**Test provider** (`local_test`): `echo`, `json` (schema-shaped sample), `tool-user` (calls its first tool once),
`scripted`, `fail`, `ratelimit`, `slow-N` (sleeps N s), `bad-json`, `stubborn`. Deterministic, free, labelled — for
tests and demos, not quality.
