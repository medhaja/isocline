# Variables and expressions

Templates use `{{path}}` and are resolved by a small path resolver — there is no `eval`.

| Root | Meaning |
|---|---|
| `{{<node_key>.output}}` | output of an upstream node, e.g. `{{research.output}}`, `{{financial.output.score}}`, `{{rows.output[0].name}}` |
| `{{input.<field>}}` | run input |
| `{{vars.<name>}}` | workflow variables (`settings.variables`) |
| `{{loop.item}}`, `{{loop.index}}` | current loop iteration |
| `{{memory.<key>}}` | workflow memory (when `workflow_memory_enabled`) |
| `{{run.id}}`, `{{run.callbacks.<wait_node_key>}}` | run metadata; signed callback URL of a `wait_webhook` node |
| `{{secret:<name>}}` | HTTP tool headers only; resolved at call time, never stored in the graph |

Paths use `.field` and `[index]`. A template that is exactly one reference keeps the value's type (object, number);
mixed with text it is rendered as text. Referencing an unknown node key is a validation error. The builder offers
typed path completion from upstream contracts.
