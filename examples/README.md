# Examples

| Example | Shows | API keys |
|---|---|---|
| [01-simple-agent](01-simple-agent/) | Simple agent | no |
| [02-multi-model](02-multi-model/) | Multi-model comparison | yes |
| [03-parallel-research](03-parallel-research/) | Parallel research | no |
| [04-human-approval](04-human-approval/) | Human approval | no |
| [05-rag](05-rag/) | Knowledge base Q&A | no |
| [06-python-analysis](06-python-analysis/) | Python analysis | no |
| [07-mcp](07-mcp/) | MCP tool | no |
| [08-durable-wait](08-durable-wait/) | Durable waits | no |
| [09-failure-recovery](09-failure-recovery/) | Failure recovery | no |
| [10-saga-compensation](10-saga-compensation/) | Saga compensation | no |
| [production-agent-demo](production-agent-demo/) | Flagship: parallel typed analysis, checkpoint, durable sign-off, report | no (optional multi-provider variant) |

Each directory has `workflow.json` (the export format: import it in the UI or via `POST /api/v1/projects/{id}/workflows/import`),
`input.json` and a README. `run_example.py` imports, performs any setup, runs and prints the result:

```bash
pip install -e sdk/python
export ISOCLINE_URL=http://localhost:8000 ISOCLINE_TOKEN=isc_pat_...
python examples/run_example.py examples/01-simple-agent
```

All examples except `02-multi-model` run on the deterministic local test provider, which returns placeholder text: it
exercises the runtime, not model quality.
