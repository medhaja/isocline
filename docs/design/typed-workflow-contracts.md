# Design: typed workflow contracts

## Problem
In visual agent builders every edge carries "some text". Errors surface at run time, deep in a model call, after money
has been spent. Structured outputs exist per model call, but nothing checks that a producer's shape matches a consumer.

## Design
Types are a small algebra (`engine/types.py`): built-ins (`Text`, `Number`, `Boolean`, `JSON`, `Table`, `File`, media
types, `Message`, `Artifact<ext>`, `Error`, `Any`), parameterised JSON (`JSON<Name>`) and workspace custom types defined
by JSON Schema. A node's `contract` declares input ports and an output port; nodes without one are `Any`.
`effective_output_type` derives a default output type from the node type (`default_output_type`) and lets
pass-through logic nodes (condition, parallel, ...) inherit the type of their single input.

`validate_contracts` checks every edge with `compatible(src, dst)`: exact matches, `Any`, safe widenings (`Number →
Text`), JSON-schema structural compatibility for custom types, and otherwise an error with a suggested transform. The
builder calls `/workflows/{id}/edge-types` to label and colour edges. At run time the executor validates inputs and
outputs against the declared schemas, enforces `max_cost`/`timeout_seconds`, and routes violations through recovery
(`contract_violation`) or `on_failure`.

## Tradeoffs
Gradual typing: untyped graphs keep working (backward compatibility with schema 1.0 documents), so guarantees are only
as strong as the annotations. Model outputs are validated, not trusted; repair costs extra calls, bounded by budgets.

## Alternatives
Nominal typing only (too rigid for JSON payloads); full structural inference from prompts (not decidable for model
outputs); run-time validation only (loses the compile-time feedback that is the point).
