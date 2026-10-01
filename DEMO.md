# Demo script (about 5 minutes)

A recording plan for a README GIF, a YouTube walkthrough or a live demo. Everything runs locally; no API key is needed
for steps 1-5 (the test provider), and step 6 shows real models.

**Setup (before recording)**

```bash
cp .env.example .env              # optionally add OPENAI_API_KEY / ANTHROPIC_API_KEY / OLLAMA_BASE_URL
docker compose up --build -d
open http://localhost:3000        # register the first account
```

**1. Templates (45 s).** Open **Templates**. Click the *Job seekers* chip, then *Content creators*, then *CEOs & founders*.
Say: "53 working multi-agent workflows — one for almost every role." Pick **Stock research brief**, choose a model.

**2. The canvas (45 s).** Show the graph: inputs → parallel fundamentals / news / risk analysts → merge → writer. Click an
agent: role, instructions, tools, model. Point at the typed edges and the variables (`{{input.ticker}}`).

**3. Run it (45 s).** Run with the sample input. Watch the three analysts light up **at the same time**. Open the run:
per-node inputs, outputs, tokens and cost.

**4. Human in the loop + durability (60 s).** Create **Board / investor update** from Templates and run it. It pauses on
*CEO approval before sending*. Now, on camera:

```bash
docker compose restart api worker
```

Back in the UI the run is still waiting. Approve it under **Approvals**; it completes. Say: "The wait lives in
PostgreSQL. No worker was held, and restarting everything lost nothing."

**5. Crash recovery (45 s).** Start `examples/production-agent-demo`, and while *research* runs:

```bash
docker compose kill -s SIGKILL worker && docker compose up -d worker
```

The run resumes on its own and finishes without re-running completed steps.

**6. Real models (30 s).** Open the *multi-provider* flagship (`examples/production-agent-demo/workflow.multi-provider.json`):
research on Ollama, financial analysis on OpenAI, risk on Anthropic, in one graph.

**7. Close (15 s).** "Open source, self-hosted, any model: `docker compose up`." Show the GitHub star button.

Tips: record at 1440×900, zoom the canvas to fit, keep the run page's *Timeline* tab open for step 3.
