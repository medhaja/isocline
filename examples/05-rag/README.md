# Knowledge base Q&A

The runner creates the *Acme handbook* knowledge base from `acme-handbook.md`, waits for ingestion, and runs an agent that retrieves from it.

**Requires:** None. For semantic (vector) retrieval set `ISOCLINE_EMBEDDING_PROVIDER=ollama` or `openai_compatible`; the default `hashing` embeddings are lexical.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/05-rag
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`; the node trace shows the retrieved refund passage.

## Notes

The workflow file uses the placeholder `__KB_ACME_HANDBOOK__`; the runner substitutes the real knowledge-base id. When importing by hand, select the knowledge base in the agent node.
