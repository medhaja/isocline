# Durable execution

A run survives worker crashes, API restarts and Redis loss because every fact needed to continue is in PostgreSQL.

| Failure | What happens |
|---|---|
| Worker process killed mid-node | heartbeat stops; after `ISOCLINE_WORKER_STALE_SECONDS` (default 60) the sweeper (every 30 s) re-enqueues the run; a worker claims it, reuses every completed node and re-runs the interrupted node |
| API restart | nothing is lost; runs execute in workers, waits live in PostgreSQL |
| Redis restart or data loss | queued messages are rebuilt from PostgreSQL by the sweeper; waiting runs are unaffected |
| Queue message duplicated | the atomic claim lets exactly one worker execute |
| Recovery keeps failing | after 3 attempts the run fails with `worker_lost` — nothing stays `running` forever |

**Guarantee:** completed nodes are never re-executed; a node that was *running* when its worker died runs again
(at-least-once). Make side-effecting steps idempotent (use the run id as an idempotency key) or give them a compensation.

**Execution limits** (per workflow, clamped to server ceilings): `max_runtime_seconds`, `max_llm_calls`,
`max_tool_calls`, `max_loop_iterations`, `max_retries_per_node`, `max_parallel_nodes`, `max_cost`, `max_total_tokens`.
Time spent waiting does not count as runtime.

Try it: `make live-check`, or `examples/production-agent-demo` → kill the worker while `research` runs.
Design: [design/durable-execution.md](design/durable-execution.md).
