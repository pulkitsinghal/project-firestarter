#!/usr/bin/env bash
# Script smoke — a fast syntax guard for the project's OWN shipped shell + python.
#
# Why: the git hooks and host-run scripts (.githooks/*, scripts/*.sh,
# backend/scripts/migrate.sh, …) are NOT exercised by the stack's Docker test
# suite. A stray quote in a hook silently disables commits; a broken migrate.sh
# only fails at deploy time. This catches those before they ship.
#
# No host SDK required (honours the no-host-SDK rule): it uses only bash + sh —
# already needed to run the hooks — and, IF python3 happens to be present, its
# stdlib py_compile. python3 is optional: absent, the .py sweep is skipped with a
# note, so this never forces a toolchain onto the host. CI runners have python3,
# so the check still runs there.
#
# Wire it into CI's "Tests" job and `make precommit`; run locally with `make smoke`.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
fail=0

# Directories to skip (vendored deps, build output, caches, throwaway profiles).
# One line, no backslash-newlines: it is expanded UNQUOTED into find's arg list.
prune='-name .git -o -name node_modules -o -name .dart_tool -o -name dist -o -name build -o -name out -o -name .next -o -name .venv -o -name __pycache__ -o -name .pytest_cache -o -name .auth'

# 1) Shell scripts → `bash -n`
# shellcheck disable=SC2086 # prune is an intentional find argument list
while IFS= read -r f; do
  bash -n "$f" || { echo "✗ bash -n: $f"; fail=1; }
done < <(find . \( $prune \) -prune -o -name '*.sh' -type f -print)

# 2) Git hooks (POSIX sh, extensionless) → `sh -n`
if [ -d .githooks ]; then
  for h in .githooks/*; do
    [ -f "$h" ] || continue
    case "$h" in *.md) continue ;; esac   # skip .githooks/README.md
    sh -n "$h" || { echo "✗ sh -n: $h"; fail=1; }
  done
fi

# 3) Python → `py_compile` (only if python3 is on PATH; never a hard host dep)
if command -v python3 >/dev/null 2>&1; then
# shellcheck disable=SC2086 # prune is an intentional find argument list
  while IFS= read -r f; do
    python3 -m py_compile "$f" || { echo "✗ py_compile: $f"; fail=1; }
  done < <(find . \( $prune \) -prune -o -name '*.py' -type f -print)
else
  echo "· python3 not found — skipping .py syntax sweep (CI runs it)."
fi

# 4) GitHub Actions → immutable remote refs. This is a dependency-free policy
# guard; firestarter's own CI separately parses every static and generated
# workflow as YAML. Local and docker actions do not use repository commit SHAs.
if [ -d .github/workflows ]; then
  while IFS= read -r f; do
    awk '
      function trim(value) {
        sub(/^[[:space:]]+/, "", value)
        sub(/[[:space:]]+$/, "", value)
        return value
      }
      function indentation(value,    count, char) {
        count = 0
        while (count < length(value)) {
          char = substr(value, count + 1, 1)
          if (char != " " && char != "\t") break
          count++
        }
        return count
      }
      function without_comment(value, initial_single, initial_double, initial_escaped,    result, i, char, next_char, in_single, in_double, escaped) {
        result = ""
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            result = result char
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            result = result char
            if (char == "\047") {
              if (next_char == "\047") {
                result = result next_char
                i++
              } else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) in_single = 1
          else if (char == "#" && (i == 1 || substr(value, i - 1, 1) ~ /[[:space:]]/)) return result
          result = result char
        }
        return result
      }
      function quote_can_open(value, position,    j, previous, prefix) {
        j = position - 1
        while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
        if (j == 0) return 1
        previous = substr(value, j, 1)
        if (previous == "?") {
          if (position <= 1 || substr(value, position - 1, 1) !~ /[[:space:]]/) return 0
          j--
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          return j == 0 || substr(value, j, 1) ~ /[:\-\[\{,?]/
        }
        if (previous == "-") {
          if (position <= 1 || substr(value, position - 1, 1) !~ /[[:space:]]/) return 0
          j--
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          return j == 0 || substr(value, j, 1) ~ /[:\-\[\{,?]/
        }
        if (previous == ":" &&
            position > 1 && substr(value, position - 1, 1) !~ /[[:space:]]/) {
          j--
          if (j <= 0) return 0
          if (flow_mapping_depth <= 0) {
            prefix = substr(value, 1, j - 1)
            if (prefix !~ /(^|[:\-\[,])[[:space:]]*[\{\[]/) return 0
          }
          return substr(value, j, 1) ~ /[\042\047\]\}]/
        }
        if (previous == ",") {
          if (flow_mapping_depth > 0) return 1
          prefix = substr(value, 1, j - 1)
          return prefix ~ /(^|[:\-\[,])[[:space:]]*[\{\[]/
        }
        if (previous == "[" || previous == "{") {
          if (flow_mapping_depth > 0) return 1
          j--
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          while (j > 0 && substr(value, j, 1) ~ /[\[\{]/) {
            j--
            while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          }
          return j == 0 || substr(value, j, 1) ~ /[:\-\[\{,?]/
        }
        return previous ~ /[:\-\[\{,?]/
      }
      function advance_quote_state(value,    i, char, next_char) {
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (yaml_in_double) {
            if (yaml_escaped) yaml_escaped = 0
            else if (char == "\\") yaml_escaped = 1
            else if (char == "\042") yaml_in_double = 0
            continue
          }
          if (yaml_in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else yaml_in_single = 0
            }
            continue
          }
          if (char == "#" && (i == 1 || substr(value, i - 1, 1) ~ /[[:space:]]/)) return
          if (char == "\042" && quote_can_open(value, i)) yaml_in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) yaml_in_single = 1
        }
      }
      function scalar_key_indentation(value, indent,    rest) {
        rest = substr(value, indent + 1)
        if (match(rest, /^-[[:space:]]+/)) return indent + RLENGTH
        return indent
      }
      function scalar_indent_indicator(value,    token, i, char) {
        if (!match(value, /[|>]([+-][1-9]|[1-9][+-]?)[[:space:]]*$/)) return 0
        token = substr(value, RSTART, RLENGTH)
        for (i = 1; i <= length(token); i++) {
          char = substr(token, i, 1)
          if (char ~ /[1-9]/) return char + 0
        }
        return 0
      }
      function flow_steps(value, initial_single, initial_double, initial_escaped,    i, char, next_char, previous, rest, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          previous = (i == 1 ? "" : substr(value, i - 1, 1))
          if (i == 1 || previous ~ /[[:space:]\{,]/) {
            rest = substr(value, i)
            if (rest ~ /^steps[[:space:]]*:[[:space:]]*\[/ ||
                rest ~ /^\042steps\042[[:space:]]*:[[:space:]]*\[/ ||
                rest ~ /^\047steps\047[[:space:]]*:[[:space:]]*\[/) return 1
          }
          if (char == "\042" && quote_can_open(value, i)) in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) in_single = 1
        }
        return 0
      }
      function flow_uses(value, initial_single, initial_double, initial_escaped,    i, j, char, next_char, previous, rest, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          previous = (i == 1 ? "" : substr(value, i - 1, 1))
          if (i > 1 && previous ~ /[[:space:]\{,]/) {
            rest = substr(value, i)
            if (rest ~ /^uses[[:space:]]*:/ ||
                rest ~ /^\042uses\042[[:space:]]*:/ ||
                rest ~ /^\047uses\047[[:space:]]*:/) {
              j = i - 1
              while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
              if (j > 0 && substr(value, j, 1) ~ /[\{,]/) return 1
            }
          }
          if (char == "\042" && quote_can_open(value, i)) in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) in_single = 1
        }
        return 0
      }
      function flow_explicit_key(value, initial_single, initial_double, initial_escaped,    i, j, char, next_char, previous, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) {
            in_double = 1
            continue
          }
          if (char == "\047" && quote_can_open(value, i)) {
            in_single = 1
            continue
          }
          if (char != "?") continue
          j = i - 1
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          if (j > 0) {
            previous = substr(value, j, 1)
            if (previous ~ /[\{,]/) return 1
          }
        }
        return 0
      }
      function yaml_anchor_or_alias(value, initial_single, initial_double, initial_escaped,    i, j, char, next_char, previous, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) {
            in_double = 1
            continue
          }
          if (char == "\047" && quote_can_open(value, i)) {
            in_single = 1
            continue
          }
          if ((char != "&" && char != "*") ||
              next_char == "" || next_char ~ /[[:space:]\[\]\{\},]/) continue
          j = i - 1
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          if (j == 0) return 1
          previous = substr(value, j, 1)
          if (previous ~ /[:\-\[\{,?]/) return 1
        }
        return 0
      }
      function yaml_node_tag(value, initial_single, initial_double, initial_escaped,    i, char, next_char, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) {
            in_double = 1
            continue
          }
          if (char == "\047" && quote_can_open(value, i)) {
            in_single = 1
            continue
          }
          if (char == "!" && quote_can_open(value, i)) return 1
        }
        return 0
      }
      function outside_at(value, target, initial_single, initial_double, initial_escaped,    i, char, next_char, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i < target; i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) in_single = 1
        }
        return !in_single && !in_double
      }
      function flow_escaped_double_key(value, initial_single, initial_double, initial_escaped,    search_start, segment, target) {
        search_start = 1
        while (search_start <= length(value)) {
          segment = substr(value, search_start)
          if (!match(segment, /\042[^\042]*\\[^\042]*\042[[:space:]]*:/)) return 0
          target = search_start + RSTART - 1
          if (outside_at(value, target, initial_single, initial_double, initial_escaped)) return 1
          search_start = target + 1
        }
        return 0
      }
      function flow_mapping_opener(value, initial_single, initial_double, initial_escaped,    i, j, char, next_char, previous, in_single, in_double, escaped) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) {
            in_double = 1
            continue
          }
          if (char == "\047" && quote_can_open(value, i)) {
            in_single = 1
            continue
          }
          if (char != "{") continue
          if (i > 1 && substr(value, i - 1, 1) == "$" ) continue
          if (i > 2 && substr(value, i - 1, 1) == "{" &&
              substr(value, i - 2, 1) == "$") continue
          j = i - 1
          while (j > 0 && substr(value, j, 1) ~ /[[:space:]]/) j--
          if (j == 0) return 1
          previous = substr(value, j, 1)
          if (previous ~ /[:\-\[,]/) return 1
        }
        return 0
      }
      function flow_brace_delta(value, initial_single, initial_double, initial_escaped,    i, char, next_char, in_single, in_double, escaped, delta) {
        in_single = initial_single
        in_double = initial_double
        escaped = initial_escaped
        delta = 0
        for (i = 1; i <= length(value); i++) {
          char = substr(value, i, 1)
          next_char = substr(value, i + 1, 1)
          if (in_double) {
            if (escaped) escaped = 0
            else if (char == "\\") escaped = 1
            else if (char == "\042") in_double = 0
            continue
          }
          if (in_single) {
            if (char == "\047") {
              if (next_char == "\047") i++
              else in_single = 0
            }
            continue
          }
          if (char == "\042" && quote_can_open(value, i)) in_double = 1
          else if (char == "\047" && quote_can_open(value, i)) in_single = 1
          else if (char == "{") delta++
          else if (char == "}") delta--
        }
        return delta
      }
      {
        line = $0
        indent = indentation(line)
        if (in_scalar) {
          if (line ~ /^[[:space:]]*$/) next
          if (scalar_body_indent < 0 && indent > scalar_key_indent) {
            scalar_body_indent = indent
            next
          }
          if (scalar_body_indent >= 0 && indent >= scalar_body_indent) next
          in_scalar = 0
        }
        if (plain_scalar_active) {
          if (line ~ /^[[:space:]]*$/) next
          if (indent > plain_scalar_indent) next
          plain_scalar_active = 0
        }
        quote_start_single = yaml_in_single
        quote_start_double = yaml_in_double
        quote_start_escaped = yaml_escaped
        visible = without_comment(line, quote_start_single, quote_start_double, quote_start_escaped)
        advance_quote_state(line)
        if (visible ~ /^[[:space:]]*$/) next
        flow_mapping_context = (flow_mapping_depth > 0)
        flow_mapping_starter = flow_mapping_opener(visible, quote_start_single, quote_start_double, quote_start_escaped)
        if (flow_mapping_context || flow_mapping_starter) {
          flow_mapping_depth += flow_brace_delta(visible, quote_start_single, quote_start_double, quote_start_escaped)
          if (flow_mapping_depth < 0) flow_mapping_depth = 0
        }
        if (pending_steps) {
          if (!quote_start_single && !quote_start_double && visible ~ /^[[:space:]]*\[/) {
            printf "✗ action ref pin: %s:%d: flow-style steps lists are not allowed\n", FILENAME, FNR
            bad = 1
            pending_steps = 0
            next
          }
          pending_steps = 0
        }
        if (pending_sequence) {
          if (!quote_start_single && !quote_start_double &&
              indent > pending_sequence_indent && visible ~ /^[[:space:]]*[\{\[]/) {
            printf "✗ action ref pin: %s:%d: flow-style sequence items are not allowed\n", FILENAME, FNR
            bad = 1
            pending_sequence = 0
            next
          }
          pending_sequence = 0
        }
        if (!quote_start_single && !quote_start_double &&
            visible ~ /^[[:space:]]*(-[[:space:]]*)?(uses|\042uses\042|\047uses\047)[[:space:]]*:[[:space:]]*[|>]/) {
          printf "✗ action ref pin: %s:%d: uses values must stay on one line\n", FILENAME, FNR
          bad = 1
          next
        }
        if (!quote_start_single && !quote_start_double &&
            visible ~ /:[[:space:]]*[|>][0-9+-]*[[:space:]]*$/) {
          in_scalar = 1
          scalar_key_indent = scalar_key_indentation(visible, indent)
          scalar_body_indent = scalar_indent_indicator(visible)
          if (scalar_body_indent > 0) scalar_body_indent += scalar_key_indent
          else scalar_body_indent = -1
          next
        }
        if (yaml_anchor_or_alias(visible, quote_start_single, quote_start_double, quote_start_escaped)) {
          printf "✗ action ref pin: %s:%d: YAML anchors and aliases are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if (yaml_node_tag(visible, quote_start_single, quote_start_double, quote_start_escaped)) {
          printf "✗ action ref pin: %s:%d: YAML node tags are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        direct_flow_steps = (!quote_start_single && !quote_start_double &&
          visible ~ /^[[:space:]]*(steps|\042steps\042|\047steps\047)[[:space:]]*:[[:space:]]*\[/)
        if ((!quote_start_single && !quote_start_double &&
             visible ~ /^[[:space:]]*-[[:space:]]*[\{\[]/) || direct_flow_steps ||
            ((flow_mapping_context || flow_mapping_starter) &&
             (flow_steps(visible, quote_start_single, quote_start_double, quote_start_escaped) ||
              flow_uses(visible, quote_start_single, quote_start_double, quote_start_escaped)))) {
          printf "✗ action ref pin: %s:%d: flow-style YAML containers are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if (!quote_start_single && !quote_start_double &&
            visible ~ /^[[:space:]]*(steps|\042steps\042|\047steps\047)[[:space:]]*:[[:space:]]*$/) {
          pending_steps = 1
          pending_steps_indent = indent
          next
        }
        if (!quote_start_single && !quote_start_double && visible ~ /^[[:space:]]*-[[:space:]]*$/) {
          pending_sequence = 1
          pending_sequence_indent = indent
          next
        }
        if (!quote_start_single && !quote_start_double &&
            visible ~ /^[[:space:]]*(-[[:space:]]*)?\042[^\042]*\\[^\042]*\042[[:space:]]*:/) {
          printf "✗ action ref pin: %s:%d: escaped double-quoted YAML mapping keys are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if ((flow_mapping_context || flow_mapping_starter) &&
            flow_escaped_double_key(visible, quote_start_single, quote_start_double, quote_start_escaped)) {
          printf "✗ action ref pin: %s:%d: escaped double-quoted YAML mapping keys are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        keyline = visible
        if (!quote_start_single && !quote_start_double &&
            keyline ~ /^[[:space:]]*(-[[:space:]]*)?\?/) {
          printf "✗ action ref pin: %s:%d: explicit YAML mapping keys are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if ((flow_mapping_context || flow_mapping_starter) &&
            flow_explicit_key(visible, quote_start_single, quote_start_double, quote_start_escaped)) {
          printf "✗ action ref pin: %s:%d: explicit YAML mapping keys are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if (!flow_mapping_context && !flow_mapping_starter &&
            !quote_start_single && !quote_start_double &&
            match(visible, /^[[:space:]]*(-[[:space:]]*)?([A-Za-z0-9_.-]+|\042[^\042]+\042|\047[^\047]+\047)[[:space:]]*:[[:space:]]+/)) {
          plain_value = substr(visible, RSTART + RLENGTH)
          if (plain_value !~ /^[\042\047\[\{|>]/) {
            plain_scalar_active = 1
            plain_scalar_indent = scalar_key_indentation(visible, indent)
          }
        } else if (!flow_mapping_context && !flow_mapping_starter &&
                   !quote_start_single && !quote_start_double &&
                   match(visible, /^[[:space:]]*-[[:space:]]+[^[:space:]]/)) {
          plain_value = substr(visible, RSTART + RLENGTH - 1)
          if (plain_value !~ /^[\042\047\[\{|>]/) {
            plain_scalar_active = 1
            plain_scalar_indent = indent
          }
        }
        if (flow_mapping_context &&
            visible ~ /^[[:space:]]*(uses|\042uses\042|\047uses\047)[[:space:]]*:/) {
          printf "✗ action ref pin: %s:%d: flow-style uses keys are not allowed\n", FILENAME, FNR
          bad = 1
          next
        }
        if (quote_start_single || quote_start_double ||
            !match(visible, /^[[:space:]]*(-[[:space:]]*)?(uses|\042uses\042|\047uses\047)[[:space:]]*:[[:space:]]*/)) {
          next
        }
        value = substr(visible, RSTART + RLENGTH)
        value = trim(value)
        if ((substr(value, 1, 1) == "\"" && substr(value, length(value), 1) == "\"") ||
            (substr(value, 1, 1) == "\047" && substr(value, length(value), 1) == "\047")) {
          value = substr(value, 2, length(value) - 2)
        }
        if (value ~ /^\.\// || value ~ /^docker:\/\//) next
        at = 0
        for (i = 1; i <= length(value); i++) {
          if (substr(value, i, 1) == "@") at = i
        }
        ref = substr(value, at + 1)
        if (!at || length(ref) != 40 || ref ~ /[^0-9A-Fa-f]/) {
          printf "✗ action ref pin: %s:%d: remote action must use a full 40-hex commit SHA\n", FILENAME, FNR
          bad = 1
        }
      }
      END { exit bad }
    ' "$f" || fail=1
  done < <(find .github/workflows -type f \( -name '*.yml' -o -name '*.yaml' \) -print)
fi

# 5) Docker gate guard → dependency-light classifier regression suite. This
# does not start Docker: fake runners prove visible, blind, and broken modes stay
# distinct, including cleanup and a removed-mount mutation.
if [ -f scripts/tests/test-gate-selftest.sh ]; then
  bash scripts/tests/test-gate-selftest.sh || fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✓ script smoke: shipped shell / hooks / python parse; workflow action refs are immutable"
fi
exit "$fail"
