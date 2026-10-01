# Troubleshooting

**`docker compose up` fails at `init-secrets` or the API cannot decrypt credentials.** The `secrets` volume was
deleted or recreated. Restore it from backup, or set `ISOCLINE_SECRET_KEY` / `ISOCLINE_ENCRYPTION_KEY` in `.env`
explicitly (stored provider keys encrypted with the old key must then be re-entered).

**Runs stay `queued`.** The worker isn't consuming: `docker compose logs worker`. It must run with
`-Q runs,ingest,maintenance`. If you customised the command, check the queues.

**Timers never fire / crashed runs are not recovered / schedules don't run.** `beat` is not running, or no worker
consumes the `maintenance` queue. `docker compose ps beat`, `docker compose logs beat`.

**Python nodes fail with "sandbox" errors.** `docker compose ps python-sandbox` shows its health; its `/healthz`
returns the exact reason (docker CLI missing, daemon unreachable because `/var/run/docker.sock` isn't mounted or
`DOCKER_HOST` is wrong — on Podman point it at the Podman socket — or the runner image missing: `docker compose build
sandbox-runner`).

**Ollama "could not reach provider".** From containers, the host is `host.docker.internal` (Compose adds the mapping
on Linux). Make Ollama listen on all interfaces (`OLLAMA_HOST=0.0.0.0`) or run Ollama as a container and set
`OLLAMA_BASE_URL=http://ollama:11434`.

**HTTP tool: "Blocked: ... resolves to a private or internal address".** Intended SSRF protection. Allow a specific
internal host with `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS='["api.internal.example"]'`.

**"Registration is closed on this installation".** Only the first account can register by default. Set
`ISOCLINE_ALLOW_SIGNUP=true` (environment provider keys are shared by all accounts).

**A 500 "Something went wrong. Reference: <id>".** Search the API log for the id: `docker compose logs api | grep <id>`;
the log line contains the traceback. Please include it (minus secrets) in bug reports.

**Web search returns nothing.** The default provider is SearXNG, which runs only with `docker compose --profile search
up`; or set `ISOCLINE_SEARCH_PROVIDER=tavily` + `TAVILY_API_KEY` (or `brave` + `BRAVE_API_KEY`).
