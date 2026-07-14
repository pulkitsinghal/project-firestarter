# Host requirements — {{ project_name }}

{{ project_name }} runs its **entire build toolchain in Docker** (see the
no-host-SDKs rule in [AGENTS.md](../AGENTS.md)). This is the short list of tools
that must — or, for native mobile, may — live on the host.

## 1. Always required (any contributor)

### Docker Desktop
All local dev runs through it. On Apple Silicon use the **ARM64** build, not the
Intel one — ARM64 runs containers natively; Intel runs under Rosetta 2 and is
markedly slower for compile-heavy work. Open Docker Desktop and confirm it's
running before any `make` / `docker compose`.

### Git + make
Both ship with the Xcode Command Line Tools on macOS:

```bash
xcode-select --install   # provides git and make
```

Verify: `git --version` · `make --version`

### GitHub CLI (`gh`)
For the PR workflow (open PRs, check CI, the auto-merge flow).

```bash
brew install gh
gh auth login
```

Verify: `gh --version`

That's it. Everything below is optional.

### Local HTTPS (optional)

When this project needs a trusted local HTTPS URL, reuse the workstation's
canonical reverse proxy and local CA rather than installing a project-specific
certificate tool. Read [LOCAL_TLS.md](LOCAL_TLS.md) and, when present,
`~/.config/pet-projects/local-tls.json`. Caddy/OpenSSL are host infrastructure in
that workflow, not project language SDKs. Importing a trust root or reloading the
live proxy remains an owner-approved operation.

## 2. What you do NOT install on the host

These are managed inside Docker (behind Compose profiles, invoked by the
Makefile). Installing them on the host won't break anything, but it invites
version drift and is not the supported path.

| Tool | Where it runs (whichever your stack uses) |
|------|-------------------------------------------|
| Python | `docker compose --profile tools` |
| Node.js / npm / pnpm | `docker compose --profile node` / `--profile splash` |
| Dart | `docker compose --profile dart` |
| Flutter | `docker compose --profile flutter` |
| `psql` / DB clients | `docker compose exec postgres psql …` |

Host **Python** and **Ruby** (the versions macOS ships) are fine for one-off
scripts; you don't install a project-specific version of either.

## 3. Native mobile (optional — only if your app targets iOS/Android)

Mobile *builds* run in Docker where possible, but **Apple's signing and
simulator stack is macOS-only** — the one hard exception to no-host-toolchains.
Skip this unless you're actively building the native mobile target.

- **iOS:** Xcode (Mac App Store), then `sudo xcode-select -s
  /Applications/Xcode.app/Contents/Developer` and `sudo xcodebuild -license
  accept`; CocoaPods via `sudo gem install cocoapods` (the system-gem version is
  the most reliable with Xcode). Simulator testing is free; a physical device or
  App Store submission needs an Apple Developer account. On Apple Silicon, some
  older pods need `arch -x86_64 pod install`.
- **Android:** the emulator needs Android Studio (`brew install --cask
  android-studio`) — pick **arm64-v8a** system images on Apple Silicon. For a
  physical device only, `brew install android-platform-tools` gives you `adb`.

## 4. Verify your setup

```bash
docker --version   # Docker running? (whale icon in the menu bar)
make --version
git --version
gh --version
```

If `docker --version` works but commands hang, Docker Desktop isn't running yet —
open it and wait for the whale icon before retrying.
