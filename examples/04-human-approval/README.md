# Human approval

A drafted email pauses on a Human Approval node. The run is persisted as WAITING and holds no worker until someone decides.

**Requires:** None.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/04-human-approval --approve
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

Without `--approve` the runner stops at `waiting`; open **Approvals** in the UI, edit/approve, and the run continues on the `approved` edge. With `--approve`: `status: completed`, `rejected` branch skipped.

## Notes

Restart the stack while it waits (`docker compose restart api worker`) — the approval survives.
