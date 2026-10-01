# Parallel research

Three branches run concurrently, a merge waits for all active branches, a writer combines them.

**Requires:** None.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/03-parallel-research
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`, 4 model calls. Each researcher uses `local_test/slow-2` (sleeps 2 s), so the run takes ~2 s, not ~6 s — concurrency is visible in the run timeline.
