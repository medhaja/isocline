## What and why

## How it was tested
- [ ] `make test` (API, OSS boundary, security, sandbox, SDK)
- [ ] `make test-web` (lint, typecheck, build) if the UI changed
- [ ] `make live-check` against a running stack if the runtime, queues or migrations changed

## Checklist
- [ ] No secrets, customer data or local paths in code, fixtures or screenshots
- [ ] Migrations: a new revision only (history is never rewritten); fresh install and upgrade both work
- [ ] Workflow JSON stays backward compatible (or the change is documented in CHANGELOG.md)
- [ ] Docs updated (README / docs/) where behaviour changed
