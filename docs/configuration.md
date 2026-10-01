# Configuration

All settings are environment variables (see `.env.example`); API settings use the `ISOCLINE_` prefix
(`apps/api/isocline/core/config.py`). Values in `.env` override generated secrets.

| Variable | Default | Meaning |
|---|---|---|
| `ISOCLINE_SECRET_KEY` | generated | session signing key |
| `ISOCLINE_ENCRYPTION_KEY` | generated | Fernet key encrypting stored credentials and webhook secrets |
| `SANDBOX_TOKEN` | generated | shared token between API and sandbox |
| `ISOCLINE_ENV` | `development` | `production` enforces explicit secrets |
| `ISOCLINE_PUBLIC_BASE_URL` | `http://localhost:3000` | used in links and callback URLs |
| `ISOCLINE_COOKIE_SECURE` | `false` | `true` behind HTTPS |
| `ISOCLINE_ALLOW_SIGNUP` | `false` | allow accounts after the first |
| `ISOCLINE_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | empty | create the admin on first start (headless) |
| `ISOCLINE_ENABLE_TEST_PROVIDER` | `true` | expose the deterministic `local_test` provider |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | empty | OpenAI |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | empty | Anthropic |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `GEMINI_BASE_URL` | empty | Google Gemini |
| `OPENROUTER_API_KEY` | empty | OpenRouter |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama |
| `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY` | empty | any OpenAI-compatible server |
| `ISOCLINE_SEARCH_PROVIDER` | `searxng` | `searxng` (profile `search`), `tavily` (`TAVILY_API_KEY`), `brave` (`BRAVE_API_KEY`) |
| `ISOCLINE_EMBEDDING_PROVIDER` | `hashing` | `hashing` (lexical, no API), `ollama`, `openai_compatible` |
| `ISOCLINE_EMBEDDING_BASE_URL`, `_API_KEY`, `_MODEL` | OpenAI defaults | embedding endpoint |
| `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS` | `[]` | JSON list of hosts the HTTP tool / MCP may reach despite being private |
| `ISOCLINE_CEILING_*` | runtime 3600 s, 500 LLM calls, 1000 tool calls, 100 loop iterations, 5 retries, 32 parallel nodes, $100, 5 M tokens | server-side safety ceilings; workflow limits are clamped to them |
| `ISOCLINE_WORKER_HEARTBEAT_SECONDS` / `_STALE_SECONDS` | 10 / 60 | heartbeat interval; a run without heartbeat for this long is recovered |
| `ISOCLINE_RATE_LIMIT_PER_MINUTE` | 120 | writes per session/IP (reads: 5×); auth: `ISOCLINE_AUTH_RATE_LIMIT_PER_MINUTE` 10 |
| `ISOCLINE_MAX_UPLOAD_MB` | 25 | upload size limit |
| `ISOCLINE_SMTP_*` | empty | email for password resets (links are logged when unset) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | export traces to your OTLP/HTTP collector |
| `SANDBOX_RUNTIME` | empty | `runsc` for gVisor |
| `SANDBOX_MEMORY`, `SANDBOX_CPUS` | `256m`, `0.5` | per-execution limits (also `SANDBOX_PIDS`=64, `SANDBOX_MAX_TIMEOUT`=60 s) |
| `WORKER_CONCURRENCY` | 4 | Celery worker processes |
