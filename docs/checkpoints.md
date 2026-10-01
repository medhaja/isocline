# Checkpoints and rerun

A checkpoint records which node runs were complete at a point in a run (and the run's totals).

Created automatically **before a side-effecting tool** (`before_side_effect`), **before a human approval**
(`before_approval`), **after an agent node that called a model** (`after_expensive`), and for sub-workflows; and
explicitly on nodes with **Harness → Checkpoint** (`"harness": {"checkpoint": true}`, reason `user`).

- **Resume from checkpoint** (run → Harness → *Resume from here*, `POST /api/v1/runs/{id}/resume {"checkpoint_id"}`,
  SDK `client.runs.resume_from_checkpoint`): a new run in the same lineage reuses every node output complete at the
  checkpoint and runs the rest. The parent must be finished.
- **Rerun from node** (run → node → *Re-run from here*, `POST /api/v1/runs/{id}/replay {"node_id"}`): a new run
  reusing all upstream outputs of that node; `use_current_draft: true` runs against the current draft graph instead of
  the original snapshot.

Reused nodes cost nothing: no model calls, no tokens. Verified live: a rerun from the second of two agents made exactly
one model call. Design: [design/checkpointing.md](design/checkpointing.md).
