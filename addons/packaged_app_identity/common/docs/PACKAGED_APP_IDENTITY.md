# Packaged-app identity & automation entitlement checks

A generic Electron / macOS packaging lesson. Two packaging failures masquerade
as application-level connector bugs, and both pass every *"does it work from my
dev shell?"* check:

1. **Automation works from a dev shell but silently no-ops from the signed
   bundle.** The packaged app is missing the Apple Events automation entitlement
   (`com.apple.security.automation.apple-events`) or its Info.plist usage
   description (`NSAppleEventsUsageDescription`). A development launch inherits
   the shell's TCC grant; the signed bundle does not.
2. **The visible build is not the installed build.** Local builds use versioned
   bundle names but share one bundle identifier and single-instance lock.
   Replacing the bundle on disk can leave the prior executable running, and
   opening the new path reactivates the *stale* process — so you verify a fix
   against a binary you did not just build.

This add-on ships `tools/packaged_app_identity/`: a stdlib-only verifier and a
host-only acceptance wrapper. Everything here is **observe / plan only** — it
reads inputs and prints a verdict or a plan. It never launches, installs,
signals, or terminates anything.

## The checks

`verify.py` is deterministic and runs on any platform (it parses property lists
and compares strings/paths; it shells out to nothing):

| Subcommand | Proves |
|---|---|
| `entitlement --entitlements <plist> [--key …]` | the extracted entitlements carry the automation entitlement, enabled (`<true/>`) |
| `usage-description --info-plist <plist> [--key …]` | the packaged `Info.plist` has a **non-empty** usage-description string |
| `identity --running-exec P --bundle B --running-identity X --bundle-identity Y` | the running executable is **inside** the installed bundle **and** its build identity matches |
| `lock-check --owner-identity X --expected-identity Y [--owner-pid N]` | the single-instance lock is held by the current build, not a stale one |
| `stop-plan --pid N [--grace S]` | emits a non-executing graceful-stop plan for **exactly one pid** |

`acceptance.sh --app /path/to/App.app` is the **one host-only acceptance
check**. It uses `codesign` to extract entitlements from a *signed bundle* —
which exists only on macOS, against a real `.app` — then feeds `verify.py`. Off
macOS it prints `SKIP` and exits 0, so a Linux CI lane stays green while the
deterministic logic is still covered by the synthetic contract test.

## Wiring it into your install / launch path

- **Build / release gate (host-only):** run `acceptance.sh --app <YourApp.app>`
  against the signed artifact. Fail the release if it fails. This catches the
  missing-entitlement class before the app ever ships.
- **Test the packaged process, not a shell-launched helper.** Automation that
  works under `swift run` / `electron .` proves nothing about the signed bundle;
  drive the real installed `.app`.
- **After a local replace, before declaring success:** read the running
  executable path and its embedded build identity, then
  `verify.py identity …` against the bundle you just installed. A mismatch means
  a stale process was reactivated.
- **At launch, when the single-instance lock is already held:**
  `verify.py lock-check …`. If a stale build owns it, **fail visibly** — do not
  silently hand control to the old process.
- **When you must stop the prior instance:** take `verify.py stop-plan --pid N`
  and act on it. Stop **only that exact pid**, gracefully. Never
  `killall`/`pkill -f` by name — that races other builds and unrelated apps.

## Content suppression (the same rule as `scripts/verify-live.sh`)

A packaged `Info.plist`, an entitlements plist, and a process path can each
carry user-identifying detail. The verifier reports by **key name**,
**basename**, and **match / mismatch** — never by dumping a plist, a full
absolute path, or a process command line. Build identities are opaque,
non-sensitive markers by contract (a version plus short commit, or a build
uuid), so they may be echoed.

## Scope

This is a generic packaging lesson. It intentionally omits private paths,
product or vendor names, UI selectors, user data, integration contracts, and
application-specific behavior. How a build identity is embedded and read back is
stack-specific; this add-on takes it as an input rather than assuming a
mechanism.
