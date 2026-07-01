# {{ project_name }} — developer command surface (fastapi-next).
# Every target dispatches to Docker; no host SDKs required. Run `make help`.

DC      := docker compose
TOOLS   := $(DC) --profile tools run --rm backend-tools
NODE    := $(DC) --profile node run --rm frontend-tools

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Stack lifecycle ──────────────────────────────────────────────────────────
.PHONY: up
up: ## Start the full stack (postgres, redis, backend, frontend)
	$(DC) up -d --build

.PHONY: down
down: ## Stop the stack and remove volumes
	$(DC) down -v

.PHONY: logs
logs: ## Tail all service logs
	$(DC) logs -f

.PHONY: migrate
migrate: ## Apply forward-only DB migrations (idempotent)
	cd backend && bash scripts/migrate.sh

# ── Backend gates (Python, in Docker) ────────────────────────────────────────
.PHONY: backend-test
backend-test: ## Run backend pytest suite
	$(TOOLS) pytest -q

.PHONY: backend-lint
backend-lint: ## ruff format-check + ruff lint + mypy
	$(TOOLS) sh -c "ruff format --check . && ruff check . && mypy app"

.PHONY: backend-fmt
backend-fmt: ## Apply ruff formatting in place
	$(TOOLS) ruff format .

# ── Frontend gates (Node, in Docker) ─────────────────────────────────────────
.PHONY: frontend-typecheck
frontend-typecheck: ## tsc --noEmit
	$(NODE) npm run typecheck

.PHONY: frontend-build
frontend-build: ## next build
	$(NODE) npm run build

# ── Aggregate gates ──────────────────────────────────────────────────────────
.PHONY: test
test: backend-test ## Run the test suite (CI "Tests" job)

.PHONY: lint
lint: backend-lint frontend-typecheck ## All lint/type checks (CI "Lint & Typecheck" job)

.PHONY: precommit
precommit: backend-lint backend-test frontend-typecheck ## Mirror CI gates locally
	@echo "✓ precommit gates passed"

# ── Storyboard & hooks ───────────────────────────────────────────────────────
.PHONY: storyboard
storyboard: ## Generate UI storyboard screenshots (Playwright in Docker → storyboard/output/)
	$(DC) --profile storyboard run --rm storyboard

.PHONY: hook-install
hook-install: ## Activate the opt-in git hooks in .githooks/
	git config core.hooksPath .githooks
	@echo "✓ hooks active (core.hooksPath=.githooks). Disable: git config --unset core.hooksPath"

# ── Beta deploy (Cloudflare quick-tunnel) ────────────────────────────────────
.PHONY: deploy
deploy: ## Expose the running frontend on a public URL (run `make up` first). See DEPLOY.md
	$(DC) --profile deploy up cloudflared

.PHONY: deploy-down
deploy-down: ## Stop the tunnel
	$(DC) --profile deploy rm -sf cloudflared

# ── Security ─────────────────────────────────────────────────────────────────
.PHONY: secret-scan
secret-scan: ## Scan the repo for committed secrets (gitleaks in Docker)
	docker run --rm -v "$$(pwd):/repo" zricethezav/gitleaks:v8.30.1 dir /repo -c /repo/.gitleaks.toml --no-banner --redact --exit-code 1

# ── Release / versioning ─────────────────────────────────────────────────────
.PHONY: version-sync
version-sync: ## Propagate /VERSION into pyproject.toml + package.json (host coreutils, no SDK)
	bash scripts/sync_version.sh
