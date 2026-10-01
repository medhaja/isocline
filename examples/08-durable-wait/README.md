# Durable waits

A 20 s timer, then a wait for an external event `payment.settled` correlated by order id.

**Requires:** None.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/08-durable-wait
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed` about 20 s after start; the runner publishes the event (`POST /api/v1/workspaces/{id}/events`) once the run is waiting for it.

## Notes

Both waits live in PostgreSQL; the beat scheduler wakes timers.
