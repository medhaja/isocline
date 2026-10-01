# Benchmarks

`run.py` measures the real implementation. It never estimates or synthesizes a number; anything it cannot measure is
reported as `NOT MEASURED`. Every result carries its sample count, and the environment (CPU, memory, OS, Python,
database/Redis versions, worker concurrency) is printed and stored with the results.

| Suite | What | Needs |
|---|---|---|
| `compile` | workflow parse + structural validation + compilation for 10 / 100 / 500-node graphs (in-process) | `pip install -r apps/api/requirements.txt` |
| `live` | queue pickup, end-to-end run, per-node overhead (50-node chain), 32-branch fan-out, durable continuation (approve → completed), HTTP tool node, knowledge search | a running stack with the local test provider |

## Reproduce

```bash
# in-process only
python benchmarks/run.py compile

# against a stack: the API under test must allow frequent polling
ISOCLINE_RATE_LIMIT_PER_MINUTE=100000 ISOCLINE_ALLOW_SIGNUP=true \
ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS='["127.0.0.1"]' docker compose up -d --build   # add these to .env instead if you prefer
BENCH_DB_VERSION="PostgreSQL 16 + pgvector" BENCH_REDIS_VERSION="Redis 7" \
python benchmarks/run.py all --base-url http://localhost:8000 --samples 30
```

Results are written to `benchmarks/results/<timestamp>.json` (not committed). For the HTTP-tool benchmark the benchmark
starts a no-op server on the machine running the script; when the API runs in Docker, that address must be reachable
and allow-listed, otherwise the benchmark reports `NOT MEASURED`.

## Reference run (2026-09-30)

Measured on the same runtime code before the repository was split out (the split removed code paths only). Re-run
`benchmarks/run.py` to measure this release on your hardware.

`reference/2026-09-30-1vcpu-no-docker.json`. **Environment:** 1 vCPU Intel Xeon @ 2.80 GHz, 3.9 GB RAM, Ubuntu 24.04,
Python 3.12.3, PostgreSQL 16.15 + pgvector 0.6.0, Redis 7.0.15, Celery prefork concurrency 2, single uvicorn API
worker, `hashing` embeddings. Processes were started directly, not in Docker. API, worker, beat, PostgreSQL and Redis
shared the single vCPU, which inflates every live number.

| Benchmark | n | P50 ms | P95 ms | P99 ms |
|---|---|---|---|---|
| compile+validate 10-node graph | 30 | 0.39 | 0.54 | 0.92 |
| compile+validate 100-node graph | 30 | 4.07 | 4.52 | 5.64 |
| compile+validate 500-node graph | 10 | 17.69 | 35.40 | 38.33 |
| queue pickup (run created → execution started) | 30 | 46.81 | 65.35 | 141.06 |
| 3-node run end-to-end, client observed (20 ms polling) | 30 | 472.33 | 569.88 | 585.06 |
| per-node overhead, 50-node sequential chain | 6 | 101.10 | 110.35 | 111.62 |
| 32-branch parallel fan-out + merge, execution time | 6 | 5410.34 | 5858.86 | 5956.30 |
| durable continuation (approve → run completed) | 15 | 396.26 | 443.84 | 460.92 |
| HTTP tool node (local no-op server) | 30 | 162.59 | 202.88 | 250.00 |
| knowledge search API (200 chunks, lexical embeddings) | 60 | 14.22 | 25.53 | 75.27 |

**Reading these numbers.** Per-node overhead (~100 ms here) is dominated by durable bookkeeping: every node run,
event and output is written to PostgreSQL before the next node is scheduled. That is the price of crash recovery and
it dominates short deterministic nodes (the 32-branch fan-out is bookkeeping-bound, not model-bound). It is the most
promising optimisation target (batching event writes); it was not optimised for this release.

**NOT MEASURED:** sandbox container startup (Docker was not available in the reference environment; process mode is
not the production isolation path and is not reported), checkpoint write/restore in isolation, Redis queue overhead
separated from Celery, event throughput, and pgvector retrieval with real (non-hashing) embeddings at scale.
