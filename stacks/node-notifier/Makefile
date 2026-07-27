# {{ project_name }} — developer command surface (node-notifier).
# Node, npm, Redis, and Playwright run in Docker; no host SDK is required.

DC := docker compose
TEST_RUN := $(DC) --profile test run --build --rm test

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: up
up: ## Build and start the API, worker, and private Redis service
	$(DC) up -d --build api worker redis
	@echo "{{ project_name }} → http://localhost:{{ port_web }}"

.PHONY: down
down: ## Stop containers while preserving queued jobs and recent results
	$(DC) down

.PHONY: clean-data
clean-data: ## Permanently remove local Redis state after an explicit cleanup choice
	$(DC) down --volumes

.PHONY: logs
logs: ## Follow API and worker logs
	$(DC) logs -f api worker

.PHONY: migrate
migrate: ## No-op — BullMQ owns its Redis key schema
	@echo "No application migration in node-notifier; BullMQ manages its Redis keys."

.PHONY: test-unit
test-unit: ## Run hermetic Node unit tests
	$(TEST_RUN) npm test

.PHONY: test-integration
test-integration: ## Run Redis-backed cross-instance and recovery tests
	$(TEST_RUN) npm run test:integration

.PHONY: test
test: ## Run unit and Redis integration suites (CI "Tests")
	$(TEST_RUN) npm run test:all

.PHONY: lint
lint: ## Syntax-check JavaScript and module entry points (CI "Lint & Typecheck")
	$(TEST_RUN) npm run check

.PHONY: build
build: ## Build the production API/worker image (CI "Build")
	$(DC) build api worker

.PHONY: smoke
smoke: ## Syntax-check shipped shell scripts, git hooks, and Python
	bash scripts/smoke.sh

.PHONY: precommit
precommit: smoke lint test build ## Mirror every required CI gate locally
	@echo "✓ precommit gates passed"

.PHONY: storyboard
storyboard: ## Capture the real lifecycle and regenerate docs/STORYBOARD.md
	@set -e; \
	  trap '$(DC) down' EXIT; \
	  PUBLIC_ORIGIN=http://api:3000 $(DC) up -d --build api worker redis; \
	  PUBLIC_ORIGIN=http://api:3000 $(DC) --profile storyboard run --rm storyboard

.PHONY: hook-install
hook-install: ## Activate the opt-in git hooks in .githooks/
	git config core.hooksPath .githooks
	@echo "✓ hooks active (core.hooksPath=.githooks). Disable: git config --unset core.hooksPath"

.PHONY: secret-scan
secret-scan: ## Scan the repository for committed secrets
	docker run --rm -v "$$(pwd):/repo" zricethezav/gitleaks:v8.30.1 dir /repo -c /repo/.gitleaks.toml --no-banner --redact --exit-code 1

.PHONY: verify-env
verify-env: ## Validate required variables declared in .env.example
	bash scripts/verify-env.sh

.PHONY: version-sync
version-sync: ## Propagate /VERSION into package manifests
	bash scripts/sync_version.sh
