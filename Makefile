PY := services/api/.venv/bin/python
.PHONY: setup dev test test-api test-web test-e2e matrix check-matrix fixtures

setup:            ## install everything for native development
	cd services/api && uv sync
	$(PY) -m playwright install chromium
	cd apps/web && pnpm install
	cd tests/e2e && pnpm install

dev:              ## run the full stack at http://localhost:8080
	./scripts/dev.sh

fixtures:
	$(PY) tests/fixtures/generate.py >/dev/null

test-api:         ## converter matrix, negative, security, lifecycle and HTTP tests (records verified.json)
	$(PY) -m pytest

test-web:         ## client-side tool unit tests (Vitest)
	cd apps/web && pnpm exec vitest run

test-e2e:         ## Playwright end-to-end tests (starts the stack if it isn't running)
	cd tests/e2e && pnpm exec playwright test

matrix:           ## regenerate docs/SUPPORT_MATRIX.md
	$(PY) scripts/support_matrix.py

check-matrix:     ## fail if an advertised-level pair has no passing test
	$(PY) scripts/support_matrix.py --check

test: test-api test-web matrix check-matrix test-e2e   ## everything
