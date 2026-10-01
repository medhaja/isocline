# Design: saga compensation

## Problem
Workflows call external systems (reserve stock, charge a card, open a ticket). When a later step fails, the earlier
effects may need undoing. Distributed transactions are not available across arbitrary HTTP APIs.

## Design
A side-effecting tool node may declare a `harness.compensation` (an `http_request` with templated arguments that can
reference the node's own output). After the node **succeeds**, the executor renders the compensation and stores a
`compensation_actions` row with a monotonically increasing `sequence`, status `available`. Nodes that failed or never
ran register nothing.

On run failure with `settings.compensation_enabled`, `run_compensations()` executes available actions ordered by
`sequence DESC`. Each passes the policy engine: `deny` → skipped; `require_approval` → skipped in automatic mode (a user
triggering compensation manually from the run page is the approval). Results are stored per action and audited.

## Properties
- Reverse order of registration = reverse order of completion, including across parallel branches (sequence is
  assigned at completion time).
- Best effort, continue on failure: one failing undo does not block the others; failures are visible and retryable
  manually.
- Never implicit: disabled unless the workflow opts in; manual execution is always available.

## Failure modes
Worker crash during compensation: actions already marked `succeeded` are not repeated when compensation is re-triggered;
an action in flight may run twice — compensations must be idempotent (e.g. DELETE by id). Compensation of a step whose
effect was partially applied depends on the target API's semantics.

## Alternatives
Two-phase commit (requires participant support); per-tool rollback code (not expressible for arbitrary HTTP); forward
recovery only (retry until success) — available through recovery rules, and complementary.
Verified live: `examples/10-saga-compensation`.
