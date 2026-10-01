# Typed contracts

A node's `contract` declares its ports and guarantees:

```json
"contract": {"inputs": [{"name": "in", "type": "Text"}],
             "output": {"name": "out", "type": "JSON<InvestmentAssessment>"},
             "capabilities": ["structured_output"], "side_effects": "none", "max_cost": 0.05, "timeout_seconds": 60}
```

Types: `Any`, `Text`, `Number`, `Boolean`, `JSON` (optionally `JSON<CustomType>`), `Table`, `File`, `Image`, `Audio`,
`Video`, `Document`, `Message`, `Message[]`, `Artifact<ext>`, `Error`, plus custom types defined as JSON Schema under
Settings → Custom types (`/workspaces/{id}/types`).

- **Compile time:** every edge's source output type is checked against the target input type. Incompatible edges are
  errors (the builder draws them red and suggests a transform); lossy but safe conversions (e.g. `Number → Text`) are
  allowed; untyped nodes are `Any`, so older workflows keep working.
- **Model capabilities:** an agent requiring `structured_output`, `tool_calling`, `vision`, ... can only run on models
  whose catalog entry has them.
- **Run time:** inputs and outputs are checked against the contract; agent `output_schema` is validated and repaired or
  retried (`structured_output` recovery), and `max_cost` / `timeout_seconds` are enforced.
- `side_effects` (`none` / `read` / `write` / `external_write`) drives caching (never cached), checkpoints (taken
  before) and compensation.

Design: [design/typed-workflow-contracts.md](design/typed-workflow-contracts.md).
