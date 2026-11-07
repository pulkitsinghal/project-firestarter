#!/usr/bin/env bash
# Host-only acceptance check for a packaged, signed macOS app bundle.
#
# This is the ONE check that cannot run anywhere else: it shells out to
# `codesign` to read the entitlements embedded in a *signed bundle*, which
# exists only on macOS and only against a real .app. Off macOS it prints SKIP
# and exits 0 so a Linux CI lane stays green; the deterministic verdict logic it
# feeds lives in verify.py and is exercised by the synthetic contract test on
# every platform.
#
# It is OBSERVE-ONLY: it reads the bundle and prints verdicts. It never installs,
# launches, signals, or modifies anything. Per the content-suppression rule it
# reports by key name only — never the entitlements or Info.plist body.
#
# Usage:
#   acceptance.sh --app /path/to/YourApp.app [--entitlement-key KEY] [--usage-key KEY]
#
# Exit: 0 pass (or skipped off macOS), 1 a check failed, 2 usage/environment error.
set -u
export LC_ALL=C

usage() {
  echo "usage: acceptance.sh --app /path/to/App.app [--entitlement-key KEY] [--usage-key KEY]" >&2
}

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
VERIFY="$SCRIPT_DIR/verify.py"

APP=""
ENT_KEY="com.apple.security.automation.apple-events"
USAGE_KEY="NSAppleEventsUsageDescription"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app)
      if [ "$#" -lt 2 ]; then echo "error: --app needs a value" >&2; exit 2; fi
      APP="$2"; shift 2 ;;
    --entitlement-key)
      if [ "$#" -lt 2 ]; then echo "error: --entitlement-key needs a value" >&2; exit 2; fi
      ENT_KEY="$2"; shift 2 ;;
    --usage-key)
      if [ "$#" -lt 2 ]; then echo "error: --usage-key needs a value" >&2; exit 2; fi
      USAGE_KEY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$APP" ]; then usage; exit 2; fi

uname_s="$(uname -s 2>/dev/null || echo unknown)"
if [ "$uname_s" != Darwin ]; then
  echo "SKIP host-only acceptance: requires macOS (uname -s=$uname_s)"
  exit 0
fi

need() { command -v "$1" >/dev/null 2>&1; }
if ! need codesign; then echo "BLOCKED codesign is not available" >&2; exit 2; fi
if ! need python3; then echo "BLOCKED python3 is not available" >&2; exit 2; fi
if [ ! -f "$VERIFY" ]; then echo "error: verify.py not found beside this script" >&2; exit 2; fi
if [ ! -d "$APP" ]; then echo "error: app bundle not found (expected a .app directory)" >&2; exit 2; fi

ent_file="$(mktemp 2>/dev/null)" || { echo "BLOCKED cannot create a temp file" >&2; exit 2; }
trap 'rm -f "$ent_file"' EXIT

# Extract entitlements from the SIGNED bundle. `:-` writes to stdout; --xml keeps
# it a parseable plist. A failure here means the bundle is unsigned or unreadable.
if ! codesign -d --entitlements :- --xml "$APP" >"$ent_file" 2>/dev/null; then
  echo "FAIL could not read code-signing entitlements from the bundle (is it signed?)" >&2
  exit 1
fi

rc=0
if ! python3 "$VERIFY" entitlement --entitlements "$ent_file" --key "$ENT_KEY"; then rc=1; fi
if ! python3 "$VERIFY" usage-description --info-plist "$APP/Contents/Info.plist" --key "$USAGE_KEY"; then rc=1; fi

if [ "$rc" -eq 0 ]; then
  echo "PASS packaged-app acceptance: entitlement + usage description present"
fi
exit "$rc"
