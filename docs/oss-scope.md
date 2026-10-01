# What this repository contains

Isocline is fully open source under Apache-2.0. Nothing in this repository is disabled, time-limited or gated behind
a license key.

**Build:** visual builder (canvas, minimap, undo/redo, autosave, notes and groups), variables and typed paths, typed
contracts and custom JSON types, JSON import/export, 50+ workflow templates.

**Nodes:** inputs (text, JSON, file, URL, chat), outputs (text, JSON, file, report, API), inline agent, tools (web
search, HTTP, Python, calculator, file reader, JSON, knowledge search), condition, router, parallel, merge, loop,
retry-until, transform, human approval, sub-workflow, timer / callback / event waits, webhook / schedule / event / file triggers.

**Run:** durable executor on PostgreSQL (parallel DAG, heartbeats, stale-run sweeper, crash recovery), checkpoints and
rerun from any node, saga compensation, durable waits that hold no worker, execution limits, policies and approvals,
caching, recovery rules and model fallbacks, Goal Mode, the Python sandbox.

**Models and tools:** OpenAI, Anthropic, Gemini, OpenRouter, Ollama, any OpenAI-compatible server, a deterministic
test provider, AUTO routing, editable model catalog and pricing, structured output, workflow memory, MCP (streamable HTTP).

**Knowledge:** knowledge bases on pgvector with upload, extraction, chunking, reprocessing and retrieval.

**Operate:** triggers, evaluations and experiments, monitoring and
drift alerts, node playground, run inspector with tokens and cost, usage, audit log.

**Develop:** REST API with OpenAPI, Python SDK, CLI, benchmarks, live durability and smoke checks.

**Accounts:** local accounts, workspaces and projects, six built-in roles (owner, admin, developer, operator,
reviewer, viewer), personal access tokens. The first account on an installation is its administrator.
