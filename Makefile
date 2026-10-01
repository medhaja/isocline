.PHONY: up down dev test test-api templates-check test-security test-sandbox test-sdk test-web lint e2e schema live-check bench licenses
PY ?= python

up:            ; docker compose up --build
down:          ; docker compose down
dev:           ; bash scripts/dev-stack.sh

lint:          ; ruff check .
test: lint test-api test-sandbox test-sdk
test-api:      ; cd apps/api && pytest -q tests
test-security: ; cd apps/api && pytest -q tests/security
test-sandbox:  ; cd workers/python-sandbox && pytest -q tests
test-sdk:      ; cd sdk/python && pytest -q tests
test-web:      ; cd apps/web && npm run lint && npm run typecheck && npm run build
e2e:           ; cd tests/e2e && npx playwright test
schema:        ; $(PY) scripts/export_schema.py
licenses:      ; $(PY) scripts/license_report.py

# Against a running stack (docker compose up). Needs ISOCLINE_ALLOW_SIGNUP=true for the throwaway test accounts.
live-check:
	$(PY) scripts/smoke_check.py --base-url http://localhost:8000
	$(PY) scripts/durability_check.py --base-url http://localhost:8000 \
	  --kill-worker "docker compose kill -s SIGKILL worker" --start-worker "docker compose up -d worker" \
	  --stop-worker "docker compose stop worker" --restart-api "docker compose restart api" \
	  --restart-redis "docker compose restart redis" --flush-redis "docker compose exec -T redis redis-cli FLUSHALL"
templates-check: ; $(PY) scripts/template_check.py --base-url http://localhost:8000   # needs ISOCLINE_TOKEN or open sign-up
bench:         ; $(PY) benchmarks/run.py all --base-url http://localhost:8000
