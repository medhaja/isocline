# Design: durable execution

## Problem
Agent workflows run for seconds to days: model calls are slow and flaky, humans approve things tomorrow, external
systems call back next week. Processes crash, deploys restart everything, and a queue broker can lose its data. The
runtime must finish every run correctly (or fail it explicitly) without holding compute while it waits.

## Constraints
- Self-hostable on commodity components (PostgreSQL, Redis, Celery); no new infrastructure to operate.
- Arbitrary DAGs with parallel branches, loops, sub-workflows and waits in any branch.
- Model and tool calls are expensive: work that completed must not be repeated after a failure.
- Operators must be able to reason about the state of every run from one database.

## Design
**PostgreSQL is the only source of truth.** A run row holds status, heartbeat, totals, the immutable graph snapshot and
clamped limits. Each node execution is a `node_runs` row (inputs, output, status, attempts, usage), each notable step
a `run_events` row. Waits are `wait_states` rows; approvals, checkpoints and compensations have their own tables.
Redis carries Celery messages and live-event fan-out only.

**Execution is a deterministic replay over persisted outcomes.** `Executor.execute()` claims the run, loads all prior
node runs, and walks the DAG: a node with a completed record returns its stored output without executing; ready nodes
run concurrently under a semaphore sized by `max_parallel_nodes`. Because outputs are persisted before downstream
nodes are scheduled, re-entering the executor at any point converges to the same state.

**Claiming** is a single conditional update (`status in (queued, resuming)` or `running` with a stale heartbeat →
`running`, set `worker_id`, `heartbeat_at`). Exactly one worker wins; duplicate messages return `not_claimed`.

**Liveness.** The executing worker updates `heartbeat_at` every 10 s. Beat runs the sweeper every 30 s: `running` runs
with a heartbeat older than `worker_stale_seconds` are re-enqueued (`recovery_attempts += 1`, max 3, then `failed`
with `worker_lost`); `queued`/`resuming` runs older than the threshold are re-enqueued (lost messages).

**Waiting holds no worker.** A wait node inserts a `wait_states` row (kind, resume time, event name + correlation,
timeout) and returns `Outcome("waiting")`; when no branch can progress, the run is persisted as `waiting` and the task
ends. Wake-ups are conditional updates on the wait row (`waiting → resumed`) followed by `waiting → resuming` on the
run and an enqueue: concurrent callback deliveries or event publishers race on the update and exactly one wins.

## State model
`queued → running → {completed | failed | cancelled | waiting}`; `waiting → resuming → running`. Node runs:
`running → {completed | failed | skipped | waiting}`. A `waiting` node run completes on resume using the wait's payload.

## Failure modes
| Failure | Outcome |
|---|---|
| worker dies mid-node | node re-executes after recovery (at-least-once); completed nodes reused |
| worker dies between persisting a node and scheduling the next | nothing lost; resume schedules it |
| API down | runs continue; waits resume when the API returns (callbacks/events need it reachable) |
| Redis loses messages | sweeper re-enqueues from PostgreSQL within `worker_stale_seconds` + 30 s |
| PostgreSQL down | everything stops; nothing is acknowledged that wasn't persisted |
| broker redelivers after visibility timeout | atomic claim rejects the duplicate |

## Tradeoffs
- At-least-once per node, not exactly-once: exactly-once would need idempotency cooperation from every external system.
  We provide run ids for idempotency keys and compensation for undo.
- Per-node persistence costs latency (~100 ms/node on a 1-vCPU reference machine, [benchmarks](../../benchmarks/README.md)).
  Batching event writes is the obvious next step.
- Recovery latency is bounded by `worker_stale_seconds` + sweeper interval (~90 s by default), not instantaneous.
- Celery `acks_late` + `reject_on_worker_lost` is kept as a second line of defence, but correctness does not depend on it.

## Alternatives considered
- **Temporal / Restate-style event-sourced replay of workflow code**: stronger semantics, but another cluster to run
  and a programming model that fights a visual, data-defined graph.
- **Holding a worker per waiting run**: simple, but a week-long approval would pin a process; rejected.
- **Redis as state store**: fast, but durability depends on AOF settings and single-node failure; rejected for
  authoritative state.
