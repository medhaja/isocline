# Design: checkpointing

## Problem
Durable execution resumes the *same* run. Users also need to go back: rerun from a node after fixing a prompt, or
resume a failed run from a known-good point, without paying again for the expensive steps before it.

## Design
A checkpoint (`checkpoints` table) stores the ids of node runs complete at that moment, the node and reason, and run
totals. Creation is cheap (no output copies: node outputs are already in `node_runs`). They are written automatically
before side-effecting tools, before approvals, after agent nodes that called a model, and for sub-workflows; and
explicitly when a node has `harness.checkpoint`.

**Resume from checkpoint** creates a child run (`parent_run_id`, `checkpoint_id`) with the parent's graph snapshot and
input, pre-populated with copies of the checkpoint's completed node runs; the executor treats them as completed and
runs the rest. **Rerun from node** derives the reuse set from the graph instead: every node upstream of the chosen node
is copied; the chosen node and everything downstream runs again (optionally against the current draft graph).

## Invariants
- A child never mutates the parent; lineage is explicit (`/runs/{id}/lineage`).
- Reused nodes cost nothing and are marked as reused in the child's trace.
- A parent must be finished before a checkpoint resume (no two executors on one lineage point).

## Failure modes and tradeoffs
- Reusing an output assumes it is still valid; side effects performed before the checkpoint are **not** replayed (by
  design) — if the external world changed, rerun earlier.
- Copying node-run rows makes children self-contained at the cost of storage proportional to reused nodes.
- A checkpoint captures node outputs, not external state; it is not a snapshot of the world.

## Alternatives
Snapshotting full run state as a blob (simpler restore, but duplicates outputs and drifts from the node-run model);
content-addressed output caching only (exists separately as the node cache, but a cache cannot express "resume this run").
