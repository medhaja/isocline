# Design: model provider abstraction

## Problem
Workflows must run on any model — hosted, local, or self-served — and switch or fall back without rewriting the graph,
while credentials stay out of the graph.

## Design
`LLMProvider` (`providers/base.py`) is the single interface: `generate(messages, model, config, tools,
response_schema, timeout) → GenerateResult` (text, tool calls, structured output, usage) and optional `list_models()`.
Adapters translate the common message/tool format into each API. `providers/registry.py` maps provider ids to classes;
the engine, validation, the model picker and one-off LLM calls resolve providers only through it — no call site
branches on provider names.

Capabilities and prices come from data (`model_catalog.json` → `model_pricing`, editable), not code: parameter
filtering (`supported_params`), capability checks for contracts and AUTO routing, and cost estimation all read it.
Errors are normalised to kinds (`rate_limit`, `timeout`, `unavailable`, `model_unavailable`, `auth`,
`structured_output`, `context_limit`) so recovery rules (retry, fallback, switch provider, reduce context) are
provider-agnostic.

Credentials are resolved per call: explicit credential → workspace credential (encrypted) → environment variables
declared by the adapter (`env_api_key`, `env_base_url`). Values are added to the run's redaction set.

## Tradeoffs
A lowest-common-denominator message format hides some provider features (they are reachable through `params` when the
catalog marks them supported). Estimated costs depend on catalog accuracy.

## Alternatives
Wrapping a third-party multi-provider SDK (fast to start; ties error semantics, release cadence and licensing to it);
per-provider node types (explodes the node library and makes switching models a graph edit).
