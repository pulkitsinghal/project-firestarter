#!/usr/bin/env bash
# Project-owned sensitive-process declarations, read by scripts/capture-guard.sh
# before any host-side screenshot / computer-use capture. Each line names ONE
# process-name pattern that must not be on screen when a capture is taken.
#
#   capture_pattern "Signal"            # exact process name
#   capture_pattern "1Password"         # a password manager
#   capture_pattern "(Messages|Mail)"   # an extended regex over the process NAME
#
# The pattern is an extended regex matched against the process name by pgrep; it
# is never echoed, so a workstation's app inventory never reaches a log, a rule
# code, or a commit. Keep it to names you would not want in a shared screenshot:
# password managers, personal messaging, a second account's mail client.
#
# A new stamp intentionally declares NOTHING, so `scripts/capture-guard.sh`
# reports SKIP rather than claiming it checked a workstation it cannot see (the
# scripts/mutation-cases.sh precedent). Declaring the first pattern is what turns
# the guard on; until then a fresh project stays green and honest.
