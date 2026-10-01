# Contributing to Isocline

Thanks for helping. This guide gets you from a clone to a tested pull request.

## Repository layout

| Path | What |
|---|---|
| `apps/api/isocline/` | FastAPI API, workflow compiler, durable executor, services, Celery worker |
| `apps/api/isocline/engine/` | graph compilation (`graph.py`), types (`types.py`), executor (`executor.py`), agent runtime, expressions, planner, policy |
| `apps/api/isocline/providers/` | model provider adapters and `registry.py` |
| `apps/api/isocline/tools/` | built-in tools (`builtin.py`), SSRF guard (`ssrf.py`) |
| `apps/api/isocline/services/` | runs, waits, triggers, knowledge, MCP, compensation, monitoring, ... |
| `apps/api/isocline/worker/` | Celery app (queues, beat schedule) and tasks |
| `apps/api/alembic/versions/` | migrations — **append only** |
| `apps/web/` | Next.js builder and operations UI |
| `workers/python-sandbox/` | sandbox controller (`app.py`) and the runner image |
| `sdk/python/` | `isocline_sdk` and the `isocline` CLI |
| `packages/workflow-schema/` | generated JSON Schema / TypeScript types for workflow documents (`make schema`) |
| `examples/`, `benchmarks/`, `scripts/` | examples + runner, benchmarks, live checks |
| `docs/` | user docs, design docs (`docs/design/`), contributor guides (`docs/contributing/`) |

## Local setup

**Everything in Docker:** `cp .env.example .env && docker compose up --build`.

**Backend without Docker** (fast iteration; needs PostgreSQL with pgvector and Redis, or use SQLite for tests):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r apps/api/requirements-dev.txt -r workers/python-sandbox/requirements.txt -e sdk/python ruff
export ISOCLINE_DATABASE_URL=postgresql+asyncpg://isocline:isocline@localhost:5432/isocline ISOCLINE_REDIS_URL=redis://localhost:6379/0
export ISOCLINE_SECRET_KEY=dev-$(python -c "import secrets;print(secrets.token_hex(16))") ISOCLINE_SANDBOX_TOKEN=dev
(cd apps/api && alembic upgrade head)
scripts/ci_stack.sh start all        # API :8000, worker, beat, sandbox (process mode needs SANDBOX_MODE=process SANDBOX_ALLOW_UNSAFE_PROCESS=true)
```

`bash scripts/dev-stack.sh` starts a lighter stack (SQLite, runs inside the API process, web on :3000) — for UI work and
the Playwright suite only; it has no crash recovery.

**Frontend:** `cd apps/web && npm ci && npm run dev` (proxies `/api` to `API_INTERNAL_URL`, default `http://localhost:8000`).

## Tests

| Command | What |
|---|---|
| `make lint` | ruff correctness rules |
| `make test-api` | unit, integration, product and security tests (SQLite, in-process dispatcher) |
| `make templates-check` | create and run every workflow template against a running stack |
| `make test-security` | SSRF suite |
| `make test-sandbox`, `make test-sdk` | sandbox controller, SDK + CLI |
| `make test-web` | frontend lint, typecheck, production build |
| `make live-check` | smoke + durability scenarios against `docker compose up` (needs `ISOCLINE_ALLOW_SIGNUP=true`) |
| `make e2e` | Playwright flows (start `scripts/dev-stack.sh` first) |

No test needs a paid API key: use the `local_test` provider (`echo`, `json`, `slow-N`, `fail`, `ratelimit`, `tool-user`, ...).

## Rules that keep the runtime trustworthy

- **Migrations are append-only.** Never edit or squash an existing revision; add a new one and make it idempotent. Test
  a fresh install *and* an upgrade on PostgreSQL (CI does both).
- **PostgreSQL is the source of truth.** Anything a run needs to resume must be in PostgreSQL; Redis may be lost at any time.
- **Nothing blocks a worker while waiting.** Waits persist state and return; they are resumed by an event, a callback,
  an approval or the beat scheduler.
- **Backward-compatible workflow JSON.** Old documents must keep loading; migrate internally and document changes.
- **Secrets never reach workflow JSON, exports, traces or logs.** Resolve them server-side at call time.
- **Honest docs and benchmarks.** Don't document behaviour the code doesn't have; never commit invented numbers.

## How to add things

- [A model provider](docs/contributing/adding-a-provider.md)
- [A tool](docs/contributing/adding-a-tool.md)
- [A node type](docs/contributing/adding-a-node.md)
- An MCP integration: usually no code — register a server ([docs/mcp.md](docs/mcp.md)); contribute an example under `examples/`.
- A document loader: text extraction lives in `apps/api/isocline/services/documents.py` (`extract_text` dispatches on
  file type); add a branch, keep it pure (bytes in, text out) and add a test.
- An embedding provider: `apps/api/isocline/services/embeddings.py` (`ISOCLINE_EMBEDDING_PROVIDER`).

## Good first issues

Provider adapters (Mistral, Bedrock, Azure OpenAI), tools and document loaders (e.g. HTML, XLSX), MCP server examples,
new examples and templates, docs, UI polish, formatter adoption across the codebase, batching executor event writes
(see the benchmark notes).

## Pull requests

Small and focused, with tests. Fill in the PR template. By contributing you agree your contribution is licensed under
Apache-2.0. Please follow the [code of conduct](CODE_OF_CONDUCT.md).
