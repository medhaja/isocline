# Changelog

Versions follow [Semantic Versioning](https://semver.org/).

## 3.3.2

### Changed
- Model prices are current: Isocline loads the community-maintained LiteLLM price list on start and daily, so new models
  (for example gpt-5.6-terra) are priced as soon as they are published. Costs, budgets and preflight use these prices.
  Prices an administrator sets (PUT /pricing) are never overwritten. `ISOCLINE_MODEL_PRICES_URL=""` turns fetching off.
- The model picker lists only models your key can use and, for hosted providers, only those with a known price, shown
  as "$ in / $ out per 1M tokens". Models that are not available are flagged instead of offered. Free-text model ids
  remain for Ollama and custom OpenAI-compatible endpoints. AUTO routing still picks only from the curated catalog.

### Fixed
- Windows desktop app: run durations and times were off by the local UTC offset (5 h 30 min in India), because SQLite
  returned timestamps without a time zone. All timestamps are now stored and returned as UTC.
- Run costs showed $0.00 for models missing from the shipped price table.

### Upgrade notes
- Migration 0003 adds `model_pricing.source`. Prices an administrator set before this release are treated as catalog
  prices and may be updated by the price list; set them again once to keep them fixed.

## 3.3.1

### Fixed
- Windows desktop app: Python steps failed with "python312.dll was not found" after reinstalling or upgrading
  Isocline. The sandbox's read access to its Python runtime is now checked on every run and restored when missing,
  instead of being remembered by file date.
- Windows desktop app: Windows no longer shows error dialogs from sandboxed Python steps; failures appear in the run.

## 3.3.0 — first public release

Isocline's first release as an open-source project (Apache-2.0). The version continues the numbering of the internal
releases it grew out of.

### Highlights
- Visual builder with typed contracts, variables and JSON import/export.
- Durable execution on PostgreSQL: parallel DAGs, heartbeats, crash recovery, checkpoints, rerun from any node,
  saga compensation, and approval / timer / callback / event waits that hold no worker.
- Any model: OpenAI, Anthropic, Gemini, OpenRouter, Ollama, any OpenAI-compatible server, and a deterministic test
  provider so everything runs without an API key.
- Sandboxed Python (one disposable, network-less container per execution; optional gVisor).
- MCP tools, knowledge bases on pgvector, webhook and schedule triggers, node playground.
- 53 workflow templates for students, job seekers, interviewers, HR, content creators, managers, investors, CEOs and
  founders, CTOs, developers, sales and marketing, researchers, teachers, customer support and freelancers.
- REST API with OpenAPI, Python SDK and CLI; benchmarks and live durability checks.
- `cp .env.example .env && docker compose up --build`: secrets are generated on first start, ports bind to localhost,
  the first account becomes the administrator.

### Interface
- Light and dark themes (follows the system setting, or choose in the sidebar), all colours as design tokens.
- Collapsible navigation rail; labelled run status on every canvas node; edges into running steps animate (disabled
  under reduced motion); bundled Instrument Sans and JetBrains Mono, no third-party font requests.

### Not included
API deployments, environment promotion (development / staging / production) and the in-builder workflow assistant are
not part of the open-source edition. Workflows run through the REST API, SDK, CLI and triggers.

### Known limitations
See the "Known limitations" section of README.md.
