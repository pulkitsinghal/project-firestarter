# {{ project_name }} — dev tasks (chrome-extension stack).
# Firestarter convention: toolchains run in Docker, never on the host. Every
# target below shells into the `node-tools` Compose service. The Playwright e2e
# suite is the exception — it needs a real headed Chromium, so it runs on host.

COMPOSE := docker compose
RUN_FLAGS :=
RUN     := $(COMPOSE) --profile tools run --rm $(RUN_FLAGS) node-tools

.DEFAULT_GOAL := help
.PHONY: help install build typecheck test-unit test lint precommit clean up down migrate storyboard e2e smoke docs-check repo-hygiene mutation-check gate-selftest gate-selftest-run verify-env verify-live release-parity hook-install

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
test: gate-selftest repo-hygiene test-unit ## Run the test suite (CI "Tests" job)

lint: typecheck ## Type-check (CI "Lint & Typecheck" job)

precommit: gate-selftest repo-hygiene smoke typecheck test-unit build ## Mirror the CI gates locally
	@echo "✓ precommit gates passed"

smoke: docs-check ## Fast shell/git-hook/doc preflight (no SDK; runs on host)
	bash scripts/smoke.sh

docs-check: ## Check required docs, local links, and Mermaid structure (no renderer)
	bash scripts/check-docs.sh

repo-hygiene: ## Scan the immutable Git index for local output, credentials, and PII shapes
	bash scripts/repo-hygiene.sh --staged

mutation-check: ## Prove configured focused tests fail under one exact source mutation
	@bash scripts/mutation-check.sh

gate-selftest: ## Prove Docker gates grade current source, never a stale image
	@$(MAKE) --no-print-directory gate-selftest-run RUN_FLAGS="--no-deps -T"

gate-selftest-run:
	@bash scripts/gate-selftest.sh \
	  --case node-tools . /work $(RUN)

verify-env: ## Check .env has every required var set (reads the .env.example manifest)
	bash scripts/verify-env.sh

verify-live: ## Verify a hosted artifact (BASE=... EXPECT=...; optional BASE_ALT/LIVE_PATH/LIVE_FIELD/LIVE_CONTAINS=1/RANGE)
	@test -n "$(BASE)" || { echo "BASE is required" >&2; exit 2; }
	@test -n "$(EXPECT)" || { echo "EXPECT is required" >&2; exit 2; }
	@set -- --expect "$(EXPECT)"; \
	  [ -z "$(LIVE_PATH)" ] || set -- "$$@" --path "$(LIVE_PATH)"; \
	  [ -z "$(LIVE_FIELD)" ] || set -- "$$@" --field "$(LIVE_FIELD)"; \
	  [ "$(LIVE_CONTAINS)" != "1" ] || set -- "$$@" --contains; \
	  [ -z "$(RANGE)" ] || set -- "$$@" --range "$(RANGE)"; \
	  set -- "$$@" "$(BASE)"; \
	  [ -z "$(BASE_ALT)" ] || set -- "$$@" "$(BASE_ALT)"; \
	  bash scripts/verify-live.sh "$$@"

override RELEASE_PARITY_PAIRS := $(value RELEASE_PARITY_PAIRS)
override RELEASE_VENDOR_MANIFEST := $(value RELEASE_VENDOR_MANIFEST)
override RELEASE_VENDOR_SOURCE := $(value RELEASE_VENDOR_SOURCE)
override RELEASE_VENDOR_RELEASE := $(value RELEASE_VENDOR_RELEASE)
export RELEASE_PARITY_PAIRS RELEASE_VENDOR_MANIFEST RELEASE_VENDOR_SOURCE RELEASE_VENDOR_RELEASE
release-parity: ## Verify deterministic release bytes (set structured RELEASE_* variables; see conventions)
	@bash scripts/verify-release-parity.sh --from-env

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
