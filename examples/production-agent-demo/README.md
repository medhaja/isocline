# Production agent demo

The flagship example: a small investment-memo pipeline that shows what the harness does under the canvas.

```
company ─► research ─► parallel ─┬─► financial (typed JSON) ─┐
                                 └─► risk      (typed JSON) ─┴─► merge [checkpoint] ─► human sign-off ─► memo ─► report.md
```

| Shown | Where |
|---|---|
| Parallel branches | `financial` and `risk` run concurrently |
| Typed data | both analysts declare `output_schema` (JSON Schema) and a `JSON` output contract; invalid output is repaired or fails the node |
| Durable HITL | `sign_off` waits up to 7 days without holding a worker; restart the stack while it waits |
| Checkpointing | `merge` records a checkpoint; resume later runs from it (run → Harness → *Resume from here*) |
| Failure recovery | kill the worker during `research` (`docker compose kill -s SIGKILL worker && docker compose up -d worker`) — the sweeper resumes the run |
| Artifacts | the report is written as `investment-memo.md` |
| Cost/tokens | per-node and per-run tokens and estimated cost on the run page; `max_llm_calls: 20` and `max_cost: 2.0` are enforced |
| Multiple providers | `workflow.multi-provider.json`: research on Ollama, financial on OpenAI, risk on Anthropic |

## Run it

```bash
python examples/run_example.py examples/production-agent-demo --approve                     # no API keys
python examples/run_example.py examples/production-agent-demo --workflow-file workflow.multi-provider.json --approve
```

Without `--approve` the run stops at the sign-off; approve it under **Approvals** in the UI.

**Expected:** `status: completed`, 4 model calls, all 9 nodes completed. With the test provider, cost is 0 and the text is
deterministic placeholder content (the test provider is not a language model).
