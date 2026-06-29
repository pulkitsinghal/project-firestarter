# {{ project_name }} — developer command surface (supabase-flutter).
# Every target dispatches to Docker; no host SDKs required. Run `make help`.

DC := docker compose

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Stack lifecycle ──────────────────────────────────────────────────────────
.PHONY: up
up: ## Start the data + API stack (postgres, redis, postgrest, gotrue)
	$(DC) up -d --build postgres redis postgrest gotrue

.PHONY: down
down: ## Stop the stack and remove volumes
	$(DC) down -v

.PHONY: logs
logs: ## Tail all service logs
	$(DC) logs -f

.PHONY: migrate
migrate: ## Apply forward-only DB migrations (idempotent)
	cd backend && bash scripts/migrate.sh

.PHONY: pgrst-reload
pgrst-reload: ## Reload PostgREST schema cache (run after every migrate)
	$(DC) restart postgrest

# ── Dart services (in Docker) ────────────────────────────────────────────────
.PHONY: dart-test
dart-test: ## Run the Dart service-layer tests
	$(DC) --profile dart run --rm dart sh -c "dart pub get && dart test"

# ── Flutter app (in Docker) ──────────────────────────────────────────────────
.PHONY: flutter-analyze
flutter-analyze: ## flutter analyze --fatal-infos
	$(DC) --profile flutter run --rm flutter sh -c "flutter pub get && flutter analyze --fatal-infos"

.PHONY: flutter-format-check
flutter-format-check: ## dart format check (read-only; exits 1 if changes needed)
	$(DC) --profile flutter run --rm flutter sh -c "dart format --output=none --set-exit-if-changed ."

.PHONY: flutter-format
flutter-format: ## Apply dart format in place
	$(DC) --profile flutter run --rm flutter sh -c "flutter pub get && dart format ."

.PHONY: flutter-test
flutter-test: ## flutter test
	$(DC) --profile flutter run --rm flutter sh -c "flutter pub get && flutter test"

# ── Splash (React + Vite, in Docker) ─────────────────────────────────────────
.PHONY: splash-check
splash-check: ## Type-check the splash page
	$(DC) --profile splash run --rm splash sh -c "corepack enable && pnpm install --frozen-lockfile && pnpm check"

.PHONY: splash-build
splash-build: ## Production build of the splash page
	$(DC) --profile splash run --rm splash sh -c "corepack enable && pnpm install --frozen-lockfile && pnpm build"

# ── Aggregate gates ──────────────────────────────────────────────────────────
.PHONY: test
test: dart-test ## Run the test suite (CI "Tests" job)

.PHONY: lint
lint: flutter-analyze flutter-format-check ## All lint/type checks (CI "Lint & Typecheck" job)

.PHONY: precommit
precommit: flutter-analyze flutter-format-check dart-test ## Mirror CI gates locally
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
deploy: ## Expose a service on a public URL (run `make up` first). See DEPLOY.md
	$(DC) --profile deploy up cloudflared

.PHONY: deploy-down
deploy-down: ## Stop the tunnel
	$(DC) --profile deploy rm -sf cloudflared
