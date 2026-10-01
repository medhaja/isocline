# Quickstart

```bash
git clone <repository-url> isocline && cd isocline
cp .env.example .env            # works unchanged; secrets are generated on first start
docker compose up --build       # first build takes several minutes
```

1. Open http://localhost:3000 and **create an account**. The first account becomes the administrator and gets a
   *Default project*. (Later sign-ups are closed unless `ISOCLINE_ALLOW_SIGNUP=true`.)
2. In the project, **Import** `examples/01-simple-agent/workflow.json`, then **Run** with `{"company": "Acme Corp"}`.
   It uses the `local_test` provider, so no key is needed. Its output is deterministic placeholder text.
3. Open the run: timeline, per-node inputs/outputs, tokens and cost, events.
4. Add a real model: put `OPENAI_API_KEY=...` (or `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL`) in `.env`
   and `docker compose up -d`, or add a key under **Keys & secrets**. Change the agent node's model and run again.
5. Try the flagship demo: import `examples/production-agent-demo/workflow.json`, run it, approve the sign-off under
   **Approvals**. Restart the stack while it waits (`docker compose restart api worker`) — it resumes.

From a terminal (Settings → **Access tokens** creates `isc_pat_...`):

```bash
pip install -e sdk/python
export ISOCLINE_URL=http://localhost:8000 ISOCLINE_TOKEN=isc_pat_...
isocline workflows list
python examples/run_example.py examples/08-durable-wait
```

Next: [self-hosting](self-hosting.md), [nodes](nodes.md), [durable execution](durable-execution.md).
