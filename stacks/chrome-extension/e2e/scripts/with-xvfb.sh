#!/usr/bin/env bash
# Run a command under a virtual X display (Xvfb) so a HEADED Chromium can run on
# a display-less machine (a CI runner / container). MV3 extensions only load into
# a headed browser, so the Playwright e2e suite can't go headless — this is how
# you still gate it in CI.
#
# Gotchas baked in (learned running headed Chrome in CI):
#   • Idempotent start — reuse an Xvfb already on the target display (pgrep
#     guard); starting a second server on a taken display errors out.
#   • Do NOT kill Xvfb on exit — other steps in the same job may still need the
#     display. Leave it for the runner to reap.
#   • Pair with container-safe Chromium flags (--no-sandbox,
#     --disable-dev-shm-usage) — set in e2e/fixtures/extension.ts.
#
# Usage:  bash scripts/with-xvfb.sh npm run test:e2e
# Needs Xvfb on PATH (ubuntu: `sudo apt-get install -y xvfb`). If Xvfb is absent
# (e.g. a real desktop with a display) it just runs the command as-is.
set -uo pipefail

DISPLAY_NUM="${XVFB_DISPLAY:-:99}"

if command -v Xvfb >/dev/null 2>&1; then
  if ! pgrep -x Xvfb >/dev/null 2>&1; then
    Xvfb "$DISPLAY_NUM" -screen 0 1920x1080x24 >/dev/null 2>&1 &
    sleep 2   # let the server come up before clients connect
  fi
  export DISPLAY="$DISPLAY_NUM"
else
  echo "· Xvfb not found — running with the current display ($DISPLAY_NUM assumed)."
fi

exec "$@"
