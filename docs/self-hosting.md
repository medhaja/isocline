# Self-hosting

## Services

| Service | Role | Port |
|---|---|---|
| `web` | Next.js UI; proxies `/api` and `/v1` to the API | 127.0.0.1:3000 |
| `api` | FastAPI; runs migrations on start (`alembic upgrade head`) | 127.0.0.1:8000 |
| `worker` | Celery worker, queues `runs,ingest,maintenance` | — |
| `beat` | Celery beat: stale-run sweeper (30 s), durable waits (5 s), schedules (20 s), drift (1 h) | — |
| `python-sandbox` | sandbox controller; starts one container per execution | internal 8100 |
| `postgres` | PostgreSQL 16 + pgvector: **authoritative state** | internal |
| `redis` | queue, cache, live events, rate limits (AOF on; losing it loses no durable state) | internal |
| `init-secrets` | one-shot: generates secrets into the `secrets` volume on first start | — |
| `sandbox-runner` | one-shot: builds the image user code runs in | — |
| `searxng` | optional (`--profile search`): web search without an API key | internal |

## Resources

Approximate, not benchmarked across machines: **minimum** 2 vCPU / 4 GB RAM / 10 GB disk (images ≈ 3–4 GB);
**recommended** 4 vCPU / 8 GB RAM. Each sandbox execution adds up to `SANDBOX_MEMORY` (256 MB) and `SANDBOX_CPUS`
(0.5). Tune `WORKER_CONCURRENCY` (default 4) to your CPU count. Local models via Ollama need their own resources.

## Exposing an installation

Ports bind to 127.0.0.1 by design. Before exposing Isocline beyond your machine:

1. Put it behind a TLS reverse proxy (Caddy, nginx, Traefik) that forwards to `web:3000` (and `api:8000` if you call the
   API directly). Set `ISOCLINE_PUBLIC_BASE_URL=https://your.host` and `ISOCLINE_COOKIE_SECURE=true`.
2. Keep `ISOCLINE_ALLOW_SIGNUP=false` unless every account holder may use the provider keys in `.env` (environment
   keys are shared by all accounts).
3. Set `ISOCLINE_ENV=production`: the API then refuses to start without explicit `ISOCLINE_SECRET_KEY` and
   `ISOCLINE_ENCRYPTION_KEY`, and warns if the test provider is enabled (`ISOCLINE_ENABLE_TEST_PROVIDER=false`).
4. Change `POSTGRES_PASSWORD` if you publish the database port (the default does not).
5. Read [sandbox.md](sandbox.md): the sandbox controller mounts the Docker socket.

## Backups

Back up the `pgdata` volume (or `pg_dump`) **and** the `secrets` volume (or your own `.env` secrets): without the
encryption key, stored provider credentials cannot be decrypted. `uploads` holds documents and artifacts. Redis does not
need a backup.

## Upgrades

`git pull && docker compose up -d --build`. Migrations run on API start; they only add tables, columns, constraints and
indexes and never rewrite history. See [CHANGELOG.md](../CHANGELOG.md) for per-release notes.

## Running without Docker

`scripts/ci_stack.sh start all` runs API, worker, beat and the sandbox as processes against your PostgreSQL and Redis
(this is how CI runs the live checks). The sandbox then needs Docker on the host, or the explicitly unsafe
`SANDBOX_MODE=process SANDBOX_ALLOW_UNSAFE_PROCESS=true` for development.

Telemetry: none. Isocline sends nothing anywhere unless you configure `OTEL_EXPORTER_OTLP_ENDPOINT` (your collector),
SMTP, model providers or tools. The web image disables Next.js build telemetry and fonts are bundled.
