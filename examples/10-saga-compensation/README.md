# Saga compensation

reserve → charge → ship (HTTP calls with registered compensations) → a failing step. With `compensation_enabled`, compensations run in reverse order.

**Requires:** A reachable API. The runner starts a mock on port 18099 and uses `http://host.docker.internal:18099`; allow it with `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS=["host.docker.internal"]`.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/10-saga-compensation
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

The run **fails by design**; the runner prints `POST /reserve -> POST /charge -> POST /ship -> DELETE /ship -> DELETE /charge -> DELETE /reserve` and `saga compensation verified`.
