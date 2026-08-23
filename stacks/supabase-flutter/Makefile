# {{ project_name }} — developer command surface (supabase-flutter).
# Every target dispatches to Docker; no host SDKs required. Run `make help`.

DC := docker compose
RUN_FLAGS :=
DART_RUN := $(DC) --profile dart run --rm $(RUN_FLAGS) dart
FLUTTER_RUN := $(DC) --profile flutter run --rm $(RUN_FLAGS) flutter
SPLASH_RUN := $(DC) --profile splash run --rm $(RUN_FLAGS) splash

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
	$(DART_RUN) sh -c "dart pub get && dart test"

# ── Flutter app (in Docker) ──────────────────────────────────────────────────
.PHONY: flutter-analyze
flutter-analyze: ## flutter analyze --fatal-infos
	$(FLUTTER_RUN) sh -c "flutter pub get && flutter analyze --fatal-infos"

.PHONY: flutter-format-check
flutter-format-check: ## dart format check (read-only; exits 1 if changes needed)
	$(FLUTTER_RUN) sh -c "dart format --output=none --set-exit-if-changed ."

.PHONY: flutter-format
flutter-format: ## Apply dart format in place
	$(FLUTTER_RUN) sh -c "flutter pub get && dart format ."

.PHONY: flutter-test
flutter-test: ## flutter test
	$(FLUTTER_RUN) sh -c "flutter pub get && flutter test"

# ── Splash (React + Vite, in Docker) ─────────────────────────────────────────
.PHONY: splash-check
splash-check: ## Type-check the splash page
	$(SPLASH_RUN) sh -c "corepack enable && pnpm install --frozen-lockfile && pnpm check"

.PHONY: splash-build
splash-build: ## Production build of the splash page
	$(SPLASH_RUN) sh -c "corepack enable && pnpm install --frozen-lockfile && pnpm build"

# ── Aggregate gates ──────────────────────────────────────────────────────────
.PHONY: test
test: gate-selftest repo-hygiene dart-test flutter-test ## Run the test suite (CI "Tests" job)

.PHONY: lint
lint: flutter-analyze flutter-format-check ## All lint/type checks (CI "Lint & Typecheck" job)

.PHONY: smoke docs-check
smoke: docs-check ## Fast shell/git-hook/doc preflight (no SDK)
	bash scripts/smoke.sh

docs-check: ## Check required docs, local links, and Mermaid structure (no renderer)
	bash scripts/check-docs.sh

.PHONY: repo-hygiene
repo-hygiene: ## Scan the immutable Git index for local output, credentials, and PII shapes
	bash scripts/repo-hygiene.sh --staged

.PHONY: mutation-check
mutation-check: ## Prove configured focused tests fail under one exact source mutation
	@bash scripts/mutation-check.sh

.PHONY: gate-selftest gate-selftest-run
gate-selftest: ## Prove Docker gates grade current source, never a stale image
	@$(MAKE) --no-print-directory gate-selftest-run RUN_FLAGS="--no-deps -T"

gate-selftest-run:
	@bash scripts/gate-selftest.sh \
	  --case dart services /pkg $(DART_RUN) \
	  --case flutter app /app $(FLUTTER_RUN) \
	  --case splash splash /splash $(SPLASH_RUN)

.PHONY: precommit
precommit: gate-selftest repo-hygiene smoke flutter-analyze flutter-format-check dart-test flutter-test ## Mirror CI gates locally
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

.PHONY: verify-live
verify-live: ## Verify deployed build (BASE=... EXPECT=...; optional BASE_ALT/LIVE_PATH/LIVE_FIELD/LIVE_CONTAINS=1/RANGE)
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

.PHONY: release-parity
override RELEASE_PARITY_PAIRS := $(value RELEASE_PARITY_PAIRS)
override RELEASE_VENDOR_MANIFEST := $(value RELEASE_VENDOR_MANIFEST)
override RELEASE_VENDOR_SOURCE := $(value RELEASE_VENDOR_SOURCE)
override RELEASE_VENDOR_RELEASE := $(value RELEASE_VENDOR_RELEASE)
export RELEASE_PARITY_PAIRS RELEASE_VENDOR_MANIFEST RELEASE_VENDOR_SOURCE RELEASE_VENDOR_RELEASE
release-parity: ## Verify deterministic release bytes (set structured RELEASE_* variables; see conventions)
	@bash scripts/verify-release-parity.sh --from-env

# ── Security ─────────────────────────────────────────────────────────────────
.PHONY: secret-scan
secret-scan: ## Scan the repo for committed secrets (gitleaks in Docker)
	docker run --rm -v "$$(pwd):/repo" zricethezav/gitleaks:v8.30.1 dir /repo -c /repo/.gitleaks.toml --no-banner --redact --exit-code 1

.PHONY: verify-env
verify-env: ## Check .env has every required var set (reads the .env.example manifest)
	bash scripts/verify-env.sh

.PHONY: rotate-secrets
rotate-secrets: ## Mint fresh JWT_SECRET/DB_PASSWORD/anon/service off the dev defaults → .env.deploy (chmod 600). Apply: docker compose --env-file .env.deploy up
	bash scripts/rotate-secrets.sh

# ── Release / versioning ─────────────────────────────────────────────────────
.PHONY: version-sync
version-sync: ## Propagate /VERSION into pubspec.yaml + splash package.json (host coreutils, no SDK)
	bash scripts/sync_version.sh
