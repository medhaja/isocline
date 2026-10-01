# Node reference

| Category | Type | Purpose / key config |
|---|---|---|
| Input | `input_text`, `input_json`, `input_file`, `input_url`, `input_chat` | read `field` from the run input; `required`, `default`, `json_schema`; file inputs can pass an artifact reference (`as_artifact`) |
| Output | `output_text`, `output_json`, `output_file`, `output_report`, `output_api` | `template` (empty = pass through), `format` (`text`/`json`/`markdown`/`file`), `filename`, `json_schema` |
| Agent | `agent` | `model` `{provider, model}`, `instructions`, `role`, `prompt`, `params`, `tools`, `knowledge_base_ids`, `output_schema` (structured output), `fallbacks`, `retry`, `timeout_seconds`, `max_tool_iterations`, `memory`, `context`, `on_failure`; `template` / `library_agent_id` start from an agent template or library agent |
| Tools | `tool_web_search`, `tool_http`, `tool_python`, `tool_calculator`, `tool_file_reader`, `tool_json`, `tool_vector_search` | `arguments` (templated), `timeout_seconds`, `retry`, `on_failure`; see [tools](tools.md) |
| Logic | `condition` | `rule {left, operator, right}` → edges `true` / `false` |
| | `router` | `routes [{name, left, operator, right}]` → an edge per route name |
| | `parallel` | fan out to every outgoing edge concurrently |
| | `merge` | `strategy` `named` / `object` / `array`; `wait_for` `all_active` / `any` |
| | `loop` | `collection` (list expression), `max_iterations`, `stop_condition`; body on `body`, continuation on `done` |
| | `retry` | retry-until: repeat the body until `stop_condition` or `max_iterations` |
| | `transform` | `mode` `template` / `select` / `json_parse` / `to_text` / `mapping` / `csv_to_table` |
| | `human_approval` | see [human in the loop](human-in-the-loop.md) |
| | `subworkflow` | `workflow_id`, pinned `version`, `input_mapping`; runs as a child run with its own trace and a budget from the parent |
| Waits | `wait_timer`, `wait_webhook`, `wait_event` | durable; hold no worker ([human-in-the-loop](human-in-the-loop.md#other-durable-waits)) |
| Triggers | `trigger_webhook`, `trigger_schedule`, `trigger_event`, `trigger_file` | entry points; output the trigger payload (optional `payload_schema`); see [triggers](triggers.md) |
| Annotation | `note`, `group` | visual only, never executed |

Every executable node also accepts `contract` ([contracts](contracts.md)) and `harness`: `cache` (`disabled` / `exact`
/ `semantic`; side-effecting steps are never cached), `sla` (latency / cost / token / attempt limits with `on_breach`),
`recovery` rules, `checkpoint`, `compensation` ([compensation](compensation.md)).
