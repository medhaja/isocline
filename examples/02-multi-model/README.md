# Multi-model comparison

The same question sent to OpenAI, Anthropic and Ollama in parallel, merged into one JSON object keyed by node.

**Requires:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and an Ollama server with `llama3.2` pulled (`OLLAMA_BASE_URL`).

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/02-multi-model
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed` with `openai_answer`, `anthropic_answer`, `ollama_answer`. Without the keys, validation reports which provider is missing and the run is not started — nothing is simulated.

## Notes

Remove any branch you don't have a key for, or point it at `local_test`.
