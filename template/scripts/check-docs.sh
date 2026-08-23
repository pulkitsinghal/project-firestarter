#!/usr/bin/env bash
# Documentation integrity preflight for stamped projects.
#
# This is deliberately a dependency-free structural guard, not a Markdown or
# Mermaid renderer. It checks publishable Markdown: required house documents,
# repository-local link paths, balanced fenced code blocks, a bounded Mermaid
# diagram-type allowlist, and the sequenceDiagram semicolon footgun. URL reachability,
# heading anchors, and full Markdown/Mermaid parsing stay outside this fast gate.

set -uo pipefail

LC_ALL=C
export LC_ALL

GIT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P) || exit 2
mode=working
case "${1:-}" in
  '') ;;
  --staged) mode=staged ;;
  *) echo "usage: scripts/check-docs.sh [--staged]" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "usage: scripts/check-docs.sh [--staged]" >&2; exit 2; }

cd "$GIT_ROOT" || exit 2

fail=0
docs=0
links=0
diagrams=0

error_at() {
  # Do not print link destinations: they can contain private/unlisted paths.
  printf '✗ docs-check: %s:%s: %s\n' "$1" "$2" "$3" >&2
  fail=1
}

if ! command -v git >/dev/null 2>&1 ||
   ! git -C "$GIT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "✗ docs-check: run inside a Git worktree" >&2
  exit 2
fi

temp_root=$(CDPATH='' cd -- "${TMPDIR:-/tmp}" && pwd -P) || {
  echo "✗ docs-check: private temporary root is unavailable" >&2
  exit 2
}
work=$(mktemp -d "$temp_root/firestarter-docs.XXXXXX") || {
  echo "✗ docs-check: could not create private temporary state" >&2
  exit 2
}
records=$work/records
# shellcheck disable=SC2329 # invoked by the signal/EXIT traps below
cleanup() {
  case "$work" in
    "$temp_root"/firestarter-docs.??????) rm -rf -- "$work" ;;
  esac
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

SCAN_ROOT=$GIT_ROOT
if [ "$mode" = staged ]; then
  index_script=$(git -C "$GIT_ROOT" rev-parse ':scripts/check-docs.sh' 2>/dev/null) || {
    echo "✗ docs-check: the staged index is missing its checker" >&2
    exit 2
  }
  working_script=$(git -C "$GIT_ROOT" hash-object "$GIT_ROOT/scripts/check-docs.sh" 2>/dev/null) || {
    echo "✗ docs-check: the working checker is unreadable" >&2
    exit 2
  }
  if [ "$index_script" != "$working_script" ]; then
    echo "✗ docs-check: the working checker differs from the staged checker" >&2
    exit 2
  fi
  SCAN_ROOT=$work/index
  mkdir "$SCAN_ROOT" || exit 2
  if ! git -C "$GIT_ROOT" checkout-index --all --prefix="$SCAN_ROOT/"; then
    echo "✗ docs-check: could not materialize the immutable staged index" >&2
    exit 2
  fi
fi
cd "$SCAN_ROOT" || exit 2

# These are the Firestarter house contract, not a product-specific doc list.
required=(
  README.md
  CHANGELOG.md
  SECURITY.md
  CONTRIBUTING.md
  ARCHITECTURE.md
  AGENTS.md
  CLAUDE.md
  VERSION
  docs/LOCAL_TLS.md
  docs/DEPLOY_POLICY.md
  docs/PRACTICES.md
  docs/SECURITY_INCIDENT_ROTATION.md
  docs/STORYBOARD.md
  docs/FEATURE_HANDOFF.md
  docs/storyboard-harness.md
)

list_publishable() {
  if [ "$mode" = staged ]; then
    git -C "$GIT_ROOT" ls-files -z --cached -- "$@"
  else
    git -C "$GIT_ROOT" ls-files -z --cached --others --exclude-standard -- "$@"
  fi
}

publishable_target_exists() {
  local wanted=$1 tracked
  while IFS= read -r -d '' tracked; do
    if [ "$tracked" = "$wanted" ] || [[ "$tracked" == "$wanted/"* ]]; then
      return 0
    fi
  done < <(list_publishable)
  return 1
}

path_has_symlink() {
  local value=$1 old_ifs part probe
  local -a parts
  old_ifs=$IFS
  IFS=/ read -r -a parts <<< "$value"
  IFS=$old_ifs
  probe=
  for part in "${parts[@]}"; do
    [ -n "$part" ] || continue
    if [ -n "$probe" ]; then probe=$probe/$part; else probe=$part; fi
    [ ! -L "$probe" ] || return 0
  done
  return 1
}

for path in "${required[@]}"; do
  if [ ! -f "$path" ] || path_has_symlink "$path" ||
     ! publishable_target_exists "$path"; then
    error_at "$path" 1 "required regular publishable project document is missing"
  fi
done

valid_iso_date() {
  local value=$1 year month day max leap
  [[ "$value" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
  year=$((10#${value:0:4}))
  month=$((10#${value:5:2}))
  day=$((10#${value:8:2}))
  [ "$month" -ge 1 ] && [ "$month" -le 12 ] || return 1
  case "$month" in
    1|3|5|7|8|10|12) max=31 ;;
    4|6|9|11) max=30 ;;
    2)
      leap=0
      if [ $((year % 400)) -eq 0 ] ||
         { [ $((year % 4)) -eq 0 ] && [ $((year % 100)) -ne 0 ]; }; then
        leap=1
      fi
      max=$((28 + leap))
      ;;
  esac
  [ "$day" -ge 1 ] && [ "$day" -le "$max" ]
}

# The seed may carry its explicit first-release placeholder. Once VERSION moves,
# the matching changelog heading must contain a concrete ISO-shaped date.
if [ -f VERSION ] && [ -f CHANGELOG.md ]; then
  version=$(tr -d '\r\n' < VERSION)
  release_date=
  while IFS= read -r line; do
    line=${line%$'\r'}
    case "$line" in
      "## [$version] - "*)
        release_date=${line#"## [$version] - "}
        break
        ;;
    esac
  done < CHANGELOG.md

  if [ -z "$release_date" ]; then
    error_at CHANGELOG.md 1 "missing a release heading for VERSION"
  elif [ "$release_date" = "YYYY-MM-DD" ]; then
    if [ "$version" != "0.1.0" ]; then
      error_at CHANGELOG.md 1 "the scaffold date placeholder is valid only for VERSION 0.1.0"
    fi
  elif ! valid_iso_date "$release_date"; then
    error_at CHANGELOG.md 1 "the VERSION release heading needs a valid ISO date"
  fi

  if ! tr -d '\r' < CHANGELOG.md | grep -Fqx '## [Unreleased]'; then
    error_at CHANGELOG.md 1 "missing the Unreleased heading"
  fi
fi

normalize_repo_path() {
  local document=$1 target=$2 base combined part count old_ifs
  local -a input output

  case "$document" in
    */*) base=${document%/*} ;;
    *) base=. ;;
  esac
  combined=$base/$target

  old_ifs=$IFS
  IFS=/ read -r -a input <<< "$combined"
  IFS=$old_ifs
  output=()
  count=0
  for part in "${input[@]}"; do
    case "$part" in
      ''|.) ;;
      ..)
        if [ "$count" -eq 0 ]; then
          return 1
        fi
        count=$((count - 1))
        unset 'output[count]'
        ;;
      *)
        output[count]=$part
        count=$((count + 1))
        ;;
    esac
  done

  if [ "$count" -eq 0 ]; then
    NORMALIZED_TARGET=.
    return 0
  fi
  NORMALIZED_TARGET=${output[0]}
  count=1
  while [ "$count" -lt "${#output[@]}" ]; do
    NORMALIZED_TARGET=$NORMALIZED_TARGET/${output[count]}
    count=$((count + 1))
  done
}

decode_url_path() {
  local encoded=$1 decoded='' char hex value octal byte i
  i=0
  while [ "$i" -lt "${#encoded}" ]; do
    char=${encoded:i:1}
    if [ "$char" != % ]; then
      decoded=$decoded$char
      i=$((i + 1))
      continue
    fi
    if [ $((i + 2)) -ge "${#encoded}" ]; then return 1; fi
    hex=${encoded:i+1:2}
    [[ "$hex" =~ ^[0-9A-Fa-f]{2}$ ]] || return 1
    value=$((16#$hex))
    # Bash strings cannot represent NUL; control bytes are not portable paths.
    [ "$value" -ge 32 ] && [ "$value" -ne 127 ] || return 1
    printf -v octal '%03o' "$value"
    printf -v byte '%b' "\\$octal"
    decoded=$decoded$byte
    i=$((i + 3))
  done
  DECODED_PATH=$decoded
}

extract_markdown_path() {
  local target=$1 extracted='' char next i
  i=0
  while [ "$i" -lt "${#target}" ]; do
    char=${target:i:1}
    case "$char" in
      '#'|'?') break ;;
      \\)
        if [ $((i + 1)) -ge "${#target}" ]; then return 1; fi
        next=${target:i+1:1}
        [[ "$next" =~ [[:punct:]] ]] || return 1
        extracted=$extracted$next
        i=$((i + 2))
        ;;
      *)
        extracted=$extracted$char
        i=$((i + 1))
        ;;
    esac
  done
  EXTRACTED_PATH=$extracted
}

check_target() {
  local document=$1 line_no=$2 target=$3 target_kind=${4:-link}
  local target_syntax=${5:-markdown} path_part

  case "$target" in
    '') return ;;
    '#'*)
      if [ "$target_kind" = resource ]; then
        error_at "$document" "$line_no" "embedded local resource must resolve to a regular file"
      fi
      return
      ;;
    '//'*) return ;;
  esac

  # Markdown destinations unescape punctuation. Raw HTML attributes do not.
  if [ "$target_syntax" = markdown ]; then
    if ! extract_markdown_path "$target"; then
      error_at "$document" "$line_no" "invalid Markdown escape in local link"
      return
    fi
    path_part=$EXTRACTED_PATH
  else
    path_part=${target%%[?#]*}
  fi
  if [ -z "$path_part" ]; then
    if [ "$target_kind" = resource ]; then
      error_at "$document" "$line_no" "embedded local resource must resolve to a regular file"
    fi
    return
  fi

  case "$path_part" in
    '//'*) return ;;
  esac
  if [[ "$path_part" =~ ^[A-Za-z]:[/\\] ]]; then
    error_at "$document" "$line_no" "local links must not use Windows drive paths"
    return
  fi
  if [[ "$path_part" =~ ^[A-Za-z][A-Za-z0-9+.-]*: ]]; then
    return
  fi

  case "$path_part" in
    /*)
      error_at "$document" "$line_no" "site-root links are not portable repository-local paths"
      return
      ;;
  esac

  if ! decode_url_path "$path_part"; then
    error_at "$document" "$line_no" "malformed or control-byte percent escape in local link"
    return
  fi
  path_part=$DECODED_PATH
  case "$path_part" in
    /*)
      error_at "$document" "$line_no" "site-root links are not portable repository-local paths"
      return
      ;;
    *\\*)
      error_at "$document" "$line_no" "local links must use portable forward slashes"
      return
      ;;
  esac
  if ! normalize_repo_path "$document" "$path_part"; then
    error_at "$document" "$line_no" "local link escapes the repository"
    return
  fi
  if [ ! -e "$NORMALIZED_TARGET" ] || path_has_symlink "$NORMALIZED_TARGET" ||
     ! publishable_target_exists "$NORMALIZED_TARGET"; then
    if [ "$target_kind" = resource ]; then
      error_at "$document" "$line_no" "embedded local resource must resolve to a regular file"
    else
      error_at "$document" "$line_no" "local link does not resolve to a regular publishable path"
    fi
    return
  fi
  if [ "$target_kind" = resource ] && [ ! -f "$NORMALIZED_TARGET" ]; then
    error_at "$document" "$line_no" "embedded local resource must resolve to a regular file"
    return
  fi
  links=$((links + 1))
}

scan_markdown() {
  awk '
    function emit(kind, line_no, detail) {
      printf "%s\t%d\t%s\n", kind, line_no, detail
    }
    function emit_reference(kind, line_no, label, target) {
      if (target ~ /[[:cntrl:]]/) {
        emit("E", line_no, "control character in reference-link destination")
        return
      }
      printf "%s\t%d\t%s\t%s\n", kind, line_no, label, target
    }
    function trim(value) {
      sub(/^[ \t]+/, "", value)
      sub(/[ \t]+$/, "", value)
      return value
    }
    function prefix_count(value, char,    i) {
      for (i = 1; i <= length(value) && substr(value, i, 1) == char; i++) { }
      return i - 1
    }
    function strip_inline_code(value,    out, i, j, run, char, in_code, ticks) {
      out = ""
      in_code = 0
      ticks = 0
      for (i = 1; i <= length(value); i++) {
        char = substr(value, i, 1)
        if (char == "`") {
          run = 1
          while (i + run <= length(value) && substr(value, i + run, 1) == "`") run++
          if (!in_code) {
            in_code = 1
            ticks = run
          } else if (run == ticks) {
            in_code = 0
            ticks = 0
          }
          for (j = 0; j < run; j++) out = out " "
          i += run - 1
        } else {
          out = out (in_code ? " " : char)
        }
      }
      return out
    }
    function strip_html_comments(value,    out, start, stop) {
      out = ""
      while (1) {
        if (html_comment) {
          stop = index(value, "-->")
          if (!stop) return out
          value = substr(value, stop + 3)
          html_comment = 0
        }
        start = index(value, "<!--")
        if (!start) return out value
        out = out substr(value, 1, start - 1)
        value = substr(value, start + 4)
        html_comment = 1
      }
    }
    function known_diagram(token,    types) {
      types = " flowchart graph sequenceDiagram classDiagram stateDiagram stateDiagram-v2 erDiagram journey gantt pie quadrantChart requirementDiagram gitGraph C4Context C4Container C4Component C4Dynamic C4Deployment mindmap timeline zenuml sankey-beta xychart-beta block-beta packet-beta kanban architecture-beta radar-beta treemap-beta venn-beta ishikawa wardley cynefin treeView info "
      return index(types, " " token " ") > 0
    }
    function normalize_label(value) {
      gsub(/[ \t]+/, " ", value)
      return tolower(trim(value))
    }
    function escaped_at(value, position,    count) {
      count = 0
      position--
      while (position > 0 && substr(value, position, 1) == "\\") {
        count++
        position--
      }
      return count % 2
    }
    function emit_target(target, line_no, kind) {
      target = trim(target)
      if (kind == "") kind = "L"
      if (target == "") {
        emit("E", line_no, "empty inline link destination")
        return
      }
      if (target ~ /[[:cntrl:]]/) {
        emit("E", line_no, "control character in link destination")
        return
      }
      emit(kind, line_no, target)
    }
    function scan_html(value, line_no,    lower, offset, found, quote_at, quote, stop, target, attribute) {
      lower = tolower(value)
      offset = 1
      while (match(substr(lower, offset), /(^|[ \t])(href|src)[ \t]*=[ \t]*["\047]/)) {
        found = offset + RSTART - 1
        quote_at = found + RLENGTH - 1
        quote = substr(value, quote_at, 1)
        stop = index(substr(value, quote_at + 1), quote)
        if (!stop) {
          emit("E", line_no, "unterminated quoted HTML link attribute")
          return
        }
        target = substr(value, quote_at + 1, stop - 1)
        attribute = substr(lower, found, RLENGTH)
        emit_target(target, line_no, attribute ~ /src/ ? "S" : "H")
        offset = quote_at + stop + 1
      }
    }
    function scan_links(value, line_no,    i, j, k, c, depth, start, target, label_end, reference, indent, label, label_text, target_kind) {
      value = strip_inline_code(value)

      # Reference definitions. Footnote definitions are prose, not link paths.
      reference = value
      sub(/^ */, "", reference)
      indent = length(value) - length(reference)
      if (indent <= 3 && match(reference, /^\[[^]]+\]:[ \t]*/)) {
        label = substr(reference, 2, index(reference, "]") - 2)
        if (substr(label, 1, 1) != "^") {
          start = RSTART + RLENGTH
          if (substr(reference, start, 1) == "<") {
            j = index(substr(reference, start + 1), ">")
            if (j > 0) emit_reference("R", line_no, normalize_label(label), substr(reference, start + 1, j - 1))
          } else {
            target = substr(reference, start)
            sub(/[ \t].*$/, "", target)
            emit_reference("R", line_no, normalize_label(label), target)
          }
        }
      }

      # Inline links/images with balanced parentheses in an unwrapped target.
      for (i = 1; i <= length(value); i++) {
        if (substr(value, i, 1) != "[" || escaped_at(value, i)) continue
        target_kind = (i > 1 && substr(value, i - 1, 1) == "!" &&
                       !escaped_at(value, i - 1)) ? "I" : "L"
        label_end = 0
        depth = 1
        for (j = i + 1; j <= length(value); j++) {
          c = substr(value, j, 1)
          if (c == "\\") {
            j++
            continue
          }
          if (c == "[") depth++
          else if (c == "]") {
            depth--
            if (depth == 0) {
              label_end = j
              break
            }
          }
        }
        if (!label_end) continue
        label_text = substr(value, i + 1, label_end - i - 1)
        if (index(label_text, "[") > 0) scan_links(label_text, line_no)
        if (substr(value, label_end + 1, 1) == "[") {
          k = label_end + 2
          while (k <= length(value) && substr(value, k, 1) != "]") k++
          if (k > length(value)) {
            emit("E", line_no, "unterminated reference-link label")
          } else {
            target = substr(value, label_end + 2, k - label_end - 2)
            if (target == "") target = substr(value, i + 1, label_end - i - 1)
            emit_reference("U", line_no, normalize_label(target), target_kind == "I" ? "resource" : "link")
          }
          i = k
          continue
        }
        if (substr(value, label_end + 1, 1) != "(") continue
        k = label_end + 2
        while (substr(value, k, 1) ~ /[ \t]/) k++
        if (substr(value, k, 1) == "<") {
          start = ++k
          while (k <= length(value) && substr(value, k, 1) != ">") k++
          if (k > length(value)) {
            emit("E", line_no, "unterminated angle-wrapped link destination")
          } else {
            emit_target(substr(value, start, k - start), line_no, target_kind)
            if (!index(substr(value, k + 1), ")")) {
              emit("E", line_no, "inline link is missing its closing parenthesis")
            }
          }
          i = k
          continue
        }

        start = k
        depth = 0
        while (k <= length(value)) {
          c = substr(value, k, 1)
          if (c == "\\") {
            k += 2
            continue
          }
          if (c == "(") depth++
          else if (c == ")") {
            if (depth == 0) break
            depth--
          } else if (c ~ /[ \t]/ && depth == 0) {
            break
          }
          k++
        }
        emit_target(substr(value, start, k - start), line_no, target_kind)
        i = k
      }
    }
    {
      line = $0
      sub(/\r$/, "", line)
      stripped = line
      sub(/^[ ]*/, "", stripped)
      indent = length(line) - length(stripped)

      if (!in_fence && indent <= 3 &&
          (prefix_count(stripped, "`") >= 3 || prefix_count(stripped, "~") >= 3)) {
        fence_char = substr(stripped, 1, 1)
        fence_len = prefix_count(stripped, fence_char)
        info = trim(substr(stripped, fence_len + 1))
        in_fence = 1
        fence_start = NR
        mermaid = (info == "mermaid")
        mermaid_first = ""
        mermaid_yaml = 0
        sequence = 0
        next
      }

      if (in_fence) {
        closing_len = prefix_count(stripped, fence_char)
        closing_rest = trim(substr(stripped, closing_len + 1))
        if (indent <= 3 && closing_len >= fence_len && closing_rest == "") {
          if (mermaid) {
            if (mermaid_first == "") emit("E", fence_start, "empty Mermaid fence")
            emit("M", fence_start, "diagram")
          }
          in_fence = 0
          next
        }
        if (mermaid && trim(line) != "") {
          if (mermaid_first == "") {
            candidate = trim(line)
            if (mermaid_yaml == 1) {
              if (candidate == "---") mermaid_yaml = 2
              next
            }
            if (mermaid_yaml == 0 && candidate == "---") {
              mermaid_yaml = 1
              next
            }
            if (substr(candidate, 1, 2) == "%%") next
            mermaid_first = candidate
            split(mermaid_first, words, /[ \t]+/)
            if (!known_diagram(words[1])) {
              emit("E", NR, "Mermaid fence does not begin with an allowlisted diagram type")
            }
            sequence = (words[1] == "sequenceDiagram")
          }
          comment = trim(line)
          if (sequence && substr(comment, 1, 2) != "%%") {
            candidate = line
            while (match(candidate, /#[[:alnum:]_]+;/)) {
              candidate = substr(candidate, 1, RSTART - 1) substr(candidate, RSTART + RLENGTH)
            }
            if (index(candidate, ";") > 0) {
              emit("E", NR, "literal semicolon in sequenceDiagram; use one statement per line and #59; for visible semicolons")
            }
          }
        }
        next
      }

      visible = strip_html_comments(line)
      if (visible ~ /^(    |\t)/) next
      scan_links(visible, NR)
      scan_html(strip_inline_code(visible), NR)
    }
    END {
      if (in_fence) emit("E", fence_start, "unclosed fenced code block")
    }
  ' < "$1"
}

while IFS= read -r -d '' document; do
  docs=$((docs + 1))
  if path_has_symlink "$document"; then
    error_at "$document" 1 "publishable Markdown source traverses a symlink"
    continue
  fi
  if ! scan_markdown "$document" > "$records"; then
    error_at "$document" 1 "documentation parser failed closed"
    continue
  fi
  ref_labels=()
  ref_lines=()
  ref_targets=()
  pending_labels=()
  pending_lines=()
  pending_kinds=()
  while IFS=$'\t' read -r kind line_no detail extra; do
    case "$kind" in
      E) error_at "$document" "$line_no" "$detail" ;;
      L) check_target "$document" "$line_no" "$detail" ;;
      I) check_target "$document" "$line_no" "$detail" resource ;;
      H) check_target "$document" "$line_no" "$detail" link html ;;
      S) check_target "$document" "$line_no" "$detail" resource html ;;
      M) diagrams=$((diagrams + 1)) ;;
      R)
        duplicate=0
        index=0
        while [ "$index" -lt "${#ref_labels[@]}" ]; do
          if [ "${ref_labels[index]}" = "$detail" ]; then duplicate=1; break; fi
          index=$((index + 1))
        done
        if [ "$duplicate" -eq 1 ]; then
          error_at "$document" "$line_no" "duplicate normalized reference-link label"
        elif [ -z "$extra" ]; then
          error_at "$document" "$line_no" "empty reference-link destination"
        else
          ref_labels[${#ref_labels[@]}]=$detail
          ref_lines[${#ref_lines[@]}]=$line_no
          ref_targets[${#ref_targets[@]}]=$extra
          check_target "$document" "$line_no" "$extra"
        fi
        ;;
      U)
        pending_labels[${#pending_labels[@]}]=$detail
        pending_lines[${#pending_lines[@]}]=$line_no
        pending_kinds[${#pending_kinds[@]}]=$extra
        ;;
    esac
  done < "$records"
  index=0
  while [ "$index" -lt "${#pending_labels[@]}" ]; do
    found=0
    ref_index=0
    while [ "$ref_index" -lt "${#ref_labels[@]}" ]; do
      if [ "${pending_labels[index]}" = "${ref_labels[ref_index]}" ]; then
        found=1
        if [ "${pending_kinds[index]}" = resource ]; then
          check_target "$document" "${pending_lines[index]}" \
            "${ref_targets[ref_index]}" resource
        fi
        break
      fi
      ref_index=$((ref_index + 1))
    done
    if [ "$found" -eq 0 ]; then
      error_at "$document" "${pending_lines[index]}" "undefined normalized reference-link label"
    fi
    index=$((index + 1))
  done
done < <(list_publishable '*.md' '*.markdown' '*.MD' '*.Markdown')

if [ "$docs" -eq 0 ]; then
  echo "✗ docs-check: no tracked Markdown files found" >&2
  exit 1
fi

if [ "$fail" -eq 0 ]; then
  printf '✓ docs-check: mode=%s docs=%d local-links=%d mermaid=%d\n' \
    "$mode" "$docs" "$links" "$diagrams"
fi
exit "$fail"
