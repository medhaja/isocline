# Simple agent

input → agent → output. The smallest useful workflow.

**Requires:** None (deterministic local test provider).

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/01-simple-agent
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`; the output is the test provider's deterministic echo of the prompt (it is not a language model). Switch the node's model to a real provider to get real text.
