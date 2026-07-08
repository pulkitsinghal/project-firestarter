# {{ project_name }} — dev tasks (chrome-extension stack).
# Firestarter convention: toolchains run in Docker, never on the host. Every
# target below shells into the `node-tools` Compose service. The Playwright e2e
# suite is the exception — it needs a real headed Chromium, so it runs on host.

COMPOSE := docker compose
RUN     := $(COMPOSE) --profile tools run --rm node-tools

.DEFAULT_GOAL := help
.PHONY: help install build typecheck test-unit test lint precommit clean up down migrate storyboard e2e smoke verify-env hook-install

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

install: ## Install deps in the container (writes extension/package-lock.json)
	$(RUN) npm install

build: ## Build the extension into extension/dist/
	$(RUN) npm run build

typecheck: ## tsc --noEmit (the type gate esbuild skips)
	$(RUN) npm run typecheck

test-unit: ## Run the Vitest unit suite
	$(RUN) npm run test:unit

clean: ## Remove extension/dist/
	$(RUN) npm run clean

# ── Meta-layer contract targets (this stack has no server/DB) ─────────────────
test: test-unit ## Run the test suite (CI "Tests" job)

lint: typecheck ## Type-check (CI "Lint & Typecheck" job)

precommit: smoke typecheck test-unit build ## Mirror the CI gates locally
	@echo "✓ precommit gates passed"

smoke: ## Syntax-check shipped shell scripts and git hooks (fast, no SDK; runs on host)
	bash scripts/smoke.sh

verify-env: ## Check .env has every required var set (reads the .env.example manifest)
	bash scripts/verify-env.sh

up: build ## Build, then load extension/dist/ as an unpacked extension
	@echo "Load it: chrome://extensions → Developer mode → Load unpacked → extension/dist/"

down: clean ## Remove the build output

migrate: ## No-op — this stack has no database
	@echo "No database in the chrome-extension stack; nothing to migrate."

# ── Storyboard (planned-vs-implemented; a firestarter precept) ────────────────
storyboard: build ## Screenshot the side panel + render docs/STORYBOARD.md
	$(COMPOSE) --profile storyboard run --rm storyboard

# ── E2E (host-only: needs a real headed Chromium) ─────────────────────────────
e2e: ## Playwright e2e — runs on the HOST (see e2e/README.md)
	@echo "E2E needs a real browser and runs on the host, not the tools container:"
	@echo "  make build && cd e2e && npm install && npm run playwright:install && npm run test:e2e"

# ── Git hooks (opt-in) ────────────────────────────────────────────────────────
hook-install: ## Activate the opt-in git hooks in .githooks/
	git config core.hooksPath .githooks
	@echo "✓ hooks active (core.hooksPath=.githooks). Disable: git config --unset core.hooksPath"
