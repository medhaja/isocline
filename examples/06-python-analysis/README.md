# Python analysis

A Python node computes statistics in the sandbox and writes `out/by_region.csv`, which becomes an artifact.

**Requires:** None (the `python-sandbox` service must be healthy).

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/06-python-analysis
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`; stdout contains `total 3500`, `mean 1166.6…`, `max 1500`; the CSV is listed under the run's artifacts.
