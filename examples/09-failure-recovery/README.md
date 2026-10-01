# Failure recovery

The primary model (`local_test/fail`) always errors. Recovery rules retry, then fall back to `local_test/echo`.

**Requires:** None.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/09-failure-recovery
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`; the node trace lists the failed attempts and the fallback that succeeded.
