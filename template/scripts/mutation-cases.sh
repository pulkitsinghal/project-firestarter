#!/usr/bin/env bash
# Project-owned mutation declarations. Keep each case focused on one guarantee
# and one named test. A new stamp intentionally has no cases, so
# `make mutation-check` reports SKIP rather than claiming mutation coverage.
#
# mutation_case \
#   "example-label" \
#   "path/to/source" \
#   "exact original fragment" \
#   "exact mutant fragment" \
#   1 \
#   -- bash scripts/prove-named-guarantee.sh
#
# The focused adapter runs in both phases. In the mutant phase, it writes
# $MUTATION_CHECK_EVIDENCE_MARKER to $MUTATION_CHECK_EVIDENCE_FILE only after it
# has recognized the intended named assertion failure.
