#!/usr/bin/env bash
# Fail-closed, content-suppressed release parity for deterministic assets.
#
# Pair manifest:   source/path<TAB>release/path
# Vendor manifest: lowercase-sha256<TAB>path-relative-to-vendor-roots
# Blank lines and tab-free lines beginning with # are ignored. A tab-bearing #
# line is a malformed row, never a comment. Paths are repository-relative,
# printable ASCII, forward-slash paths with no . or .. segments.

set +x
set -uo pipefail
export LC_ALL=C
umask 077

usage() {
  cat >&2 <<'EOF'
usage: scripts/verify-release-parity.sh [--pairs FILE]
       [--vendor-manifest FILE --vendor-source DIR --vendor-release DIR]
       scripts/verify-release-parity.sh --from-env

At least one pair manifest or the complete vendor option group is required.
--from-env reads RELEASE_PARITY_PAIRS and the complete RELEASE_VENDOR_MANIFEST,
RELEASE_VENDOR_SOURCE, RELEASE_VENDOR_RELEASE group without shell interpolation.
EOF
}

infra_error() {
  printf 'release-parity: ERROR code=%s\n' "$1" >&2
  exit 2
}

violations=0
record_violation() {
  violations=$((violations + 1))
}

for required_tool in cmp find grep mkdir rm rmdir sort tr; do
  command -v "$required_tool" >/dev/null 2>&1 \
    || infra_error "missing-tool"
done

hash_mode=
if command -v sha256sum >/dev/null 2>&1; then
  hash_mode=sha256sum
elif command -v shasum >/dev/null 2>&1; then
  hash_mode=shasum
else
  infra_error "missing-sha256-tool"
fi

pairs_manifest=
vendor_manifest=
vendor_source=
vendor_release=

if [ "$#" -eq 1 ] && [ "$1" = --from-env ]; then
  pairs_manifest=${RELEASE_PARITY_PAIRS:-}
  vendor_manifest=${RELEASE_VENDOR_MANIFEST:-}
  vendor_source=${RELEASE_VENDOR_SOURCE:-}
  vendor_release=${RELEASE_VENDOR_RELEASE:-}
  shift
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --pairs)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      [ -z "$pairs_manifest" ] || infra_error "duplicate-option"
      pairs_manifest=$2
      shift 2
      ;;
    --vendor-manifest)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      [ -z "$vendor_manifest" ] || infra_error "duplicate-option"
      vendor_manifest=$2
      shift 2
      ;;
    --vendor-source)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      [ -z "$vendor_source" ] || infra_error "duplicate-option"
      vendor_source=$2
      shift 2
      ;;
    --vendor-release)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      [ -z "$vendor_release" ] || infra_error "duplicate-option"
      vendor_release=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

vendor_option_count=0
[ -z "$vendor_manifest" ] || vendor_option_count=$((vendor_option_count + 1))
[ -z "$vendor_source" ] || vendor_option_count=$((vendor_option_count + 1))
[ -z "$vendor_release" ] || vendor_option_count=$((vendor_option_count + 1))
[ "$vendor_option_count" -eq 0 ] || [ "$vendor_option_count" -eq 3 ] \
  || infra_error "incomplete-vendor-options"
[ -n "$pairs_manifest" ] || [ "$vendor_option_count" -eq 3 ] \
  || { usage; exit 2; }

is_safe_relative_path() {
  local value=$1
  case "$value" in
    ''|-*|/*|*\\*|*//*|*/|?:*) return 1 ;;
    *[![:print:]]*) return 1 ;;
  esac
  case "/$value/" in
    */./*|*/../*) return 1 ;;
  esac
  return 0
}

has_symlink_component() {
  local value=$1
  local cursor=
  local old_ifs=$IFS
  local component
  local components
  IFS=/
  read -r -a components <<< "$value"
  IFS=$old_ifs
  for component in "${components[@]}"; do
    if [ -z "$cursor" ]; then
      cursor=$component
    else
      cursor="$cursor/$component"
    fi
    [ ! -L "$cursor" ] || return 0
  done
  return 1
}

has_exact_spelling() {
  local value=$1
  local cursor=.
  local old_ifs=$IFS
  local component
  local components
  local entry
  local found
  IFS=/
  read -r -a components <<< "$value"
  IFS=$old_ifs
  for component in "${components[@]}"; do
    found=0
    for entry in "$cursor"/* "$cursor"/.[!.]* "$cursor"/..?*; do
      [ -e "$entry" ] || [ -L "$entry" ] || continue
      if [ "${entry##*/}" = "$component" ]; then
        found=$((found + 1))
      fi
    done
    [ "$found" -eq 1 ] || return 1
    cursor="$cursor/$component"
  done
  return 0
}

is_plain_file() {
  local value=$1
  is_safe_relative_path "$value" || return 1
  has_symlink_component "$value" && return 1
  has_exact_spelling "$value" || return 1
  [ -f "$value" ] || return 1
  return 0
}

fd_reference() {
  local descriptor=$1
  if [ -e "/proc/self/fd/$descriptor" ] || [ -L "/proc/self/fd/$descriptor" ]; then
    printf '/proc/self/fd/%s' "$descriptor"
  elif [ -e "/dev/fd/$descriptor" ] || [ -L "/dev/fd/$descriptor" ]; then
    printf '/dev/fd/%s' "$descriptor"
  else
    return 1
  fi
}

is_plain_directory() {
  local value=$1
  is_safe_relative_path "$value" || return 1
  has_symlink_component "$value" && return 1
  has_exact_spelling "$value" || return 1
  [ -d "$value" ] || return 1
  return 0
}

temp_base_input=${TMPDIR:-/tmp}
temp_base=$(cd -P "$temp_base_input" 2>/dev/null && pwd -P) \
  || infra_error "private-temp-base"
case "$temp_base" in /) infra_error "private-temp-base" ;; /*) ;; *) infra_error "private-temp-base" ;; esac

# Keep the resolved parent open for the entire run. /proc/self/fd (Linux) or
# /dev/fd (macOS/BSD) gives child tools the same directory handle, so replacing
# any pathname ancestor with a symlink cannot redirect cleanup elsewhere.
exec 9< "$temp_base" || infra_error "private-temp-base"
if [ -d /proc/self/fd/9 ]; then
  temp_parent=/proc/self/fd/9
elif [ -d /dev/fd/9 ]; then
  temp_parent=/dev/fd/9
else
  infra_error "private-temp-handle"
fi
temp_root=
temp_attempt=0
while [ "$temp_attempt" -lt 32 ]; do
  temp_candidate="$temp_parent/release-parity.$$.$temp_attempt"
  if mkdir -m 700 "$temp_candidate" >/dev/null 2>&1; then
    if [ -d "$temp_candidate" ] && [ ! -L "$temp_candidate" ]; then
      temp_root=$temp_candidate
      break
    fi
    infra_error "private-temp-ownership"
  fi
  # A degraded mkdir may create an empty directory and still report failure.
  # Remove only that empty candidate; never recurse into an unowned path.
  if [ -d "$temp_candidate" ] && [ ! -L "$temp_candidate" ]; then
    rmdir "$temp_candidate" >/dev/null 2>&1 \
      || infra_error "private-temp-ownership"
  fi
  temp_attempt=$((temp_attempt + 1))
done
[ -n "$temp_root" ] || infra_error "private-temp-create"
case "$temp_root" in
  "$temp_parent"/release-parity.*) ;;
  *) infra_error "private-temp-path" ;;
esac

cleanup() {
  local cleanup_status=$?
  trap - EXIT HUP INT TERM
  case "${temp_root:-}" in
    "$temp_parent"/release-parity.*)
      if [ -e "$temp_root" ] || [ -L "$temp_root" ]; then
        rm -rf "$temp_root" >/dev/null 2>&1 || {
          printf 'release-parity: ERROR code=private-temp-cleanup\n' >&2
          [ "$cleanup_status" -ne 0 ] && exit "$cleanup_status"
          exit 2
        }
      fi
      if [ -e "$temp_root" ] || [ -L "$temp_root" ]; then
        printf 'release-parity: ERROR code=private-temp-cleanup\n' >&2
        [ "$cleanup_status" -ne 0 ] && exit "$cleanup_status"
        exit 2
      fi
      ;;
  esac
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 2' HUP INT TERM

mark_unique() {
  local value=$1
  local seen_file=$2
  local folded
  folded=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]') \
    || infra_error "path-fold"
  if grep -Fqx -- "$folded" "$seen_file" >/dev/null 2>&1; then
    return 1
  fi
  printf '%s\n' "$folded" >> "$seen_file" \
    || infra_error "private-temp-write"
  return 0
}

fold_path() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    || infra_error "path-fold"
}

hash_file() {
  local value=$1
  local output="$temp_root/hash-output"
  local digest
  if [ "$hash_mode" = sha256sum ]; then
    sha256sum "$value" > "$output" 2>/dev/null \
      || infra_error "hash-read"
  else
    shasum -a 256 "$value" > "$output" 2>/dev/null \
      || infra_error "hash-read"
  fi
  IFS=' ' read -r digest _ < "$output" \
    || infra_error "hash-output"
  case "$digest" in
    *[!0-9a-fA-F]*) infra_error "hash-output" ;;
  esac
  [ "${#digest}" -eq 64 ] || infra_error "hash-output"
  printf '%s' "$digest" | tr '[:upper:]' '[:lower:]' \
    || infra_error "hash-output"
}

verify_required_tools() {
  local probe_a="$temp_root/tool-a"
  local probe_b="$temp_root/tool-b"
  local probe_actual="$temp_root/tool-actual"
  local probe_expected="$temp_root/tool-expected"
  local probe_dir="$temp_root/tool-dir"
  local digest
  local cmp_status
  local grep_status

  printf 'b\na\n' > "$probe_a" || infra_error "tool-selftest"
  printf 'a\nb\n' > "$probe_expected" || infra_error "tool-selftest"
  sort "$probe_a" > "$probe_actual" 2>/dev/null \
    || infra_error "tool-selftest-sort"
  cmp -s "$probe_actual" "$probe_expected" >/dev/null 2>&1 \
    || infra_error "tool-selftest-sort"

  printf 'same\n' > "$probe_a" || infra_error "tool-selftest"
  printf 'same\n' > "$probe_b" || infra_error "tool-selftest"
  cmp -s "$probe_a" "$probe_b" >/dev/null 2>&1
  cmp_status=$?
  [ "$cmp_status" -eq 0 ] || infra_error "tool-selftest-cmp"
  printf 'different\n' > "$probe_b" || infra_error "tool-selftest"
  cmp -s "$probe_a" "$probe_b" >/dev/null 2>&1
  cmp_status=$?
  [ "$cmp_status" -eq 1 ] || infra_error "tool-selftest-cmp"

  grep -Fqx -- 'same' "$probe_a" >/dev/null 2>&1
  grep_status=$?
  [ "$grep_status" -eq 0 ] || infra_error "tool-selftest-grep"
  grep -Fqx -- 'absent' "$probe_a" >/dev/null 2>&1
  grep_status=$?
  [ "$grep_status" -eq 1 ] || infra_error "tool-selftest-grep"

  printf 'A-Z\n' | tr '[:upper:]' '[:lower:]' > "$probe_actual" 2>/dev/null \
    || infra_error "tool-selftest-tr"
  printf 'a-z\n' > "$probe_expected" || infra_error "tool-selftest"
  cmp -s "$probe_actual" "$probe_expected" >/dev/null 2>&1 \
    || infra_error "tool-selftest-tr"

  mkdir "$probe_dir" >/dev/null 2>&1 || infra_error "tool-selftest-mkdir"
  printf 'item\n' > "$probe_dir/item" || infra_error "tool-selftest"
  find "$probe_dir" -mindepth 1 -print0 > "$probe_actual" 2>/dev/null \
    || infra_error "tool-selftest-find"
  printf '%s\0' "$probe_dir/item" > "$probe_expected" \
    || infra_error "tool-selftest"
  cmp -s "$probe_actual" "$probe_expected" >/dev/null 2>&1 \
    || infra_error "tool-selftest-find"

  printf 'abc' > "$probe_a" || infra_error "tool-selftest"
  digest=$(hash_file "$probe_a")
  [ "$digest" = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad ] \
    || infra_error "tool-selftest-sha256"

  rm -rf "$probe_dir" >/dev/null 2>&1 \
    || infra_error "tool-selftest-rm"
  [ ! -e "$probe_dir" ] && [ ! -L "$probe_dir" ] \
    || infra_error "tool-selftest-rm"
  mkdir "$probe_dir" >/dev/null 2>&1 || infra_error "tool-selftest-mkdir"
  rmdir "$probe_dir" >/dev/null 2>&1 \
    || infra_error "tool-selftest-rmdir"
  [ ! -e "$probe_dir" ] && [ ! -L "$probe_dir" ] \
    || infra_error "tool-selftest-rmdir"
}

verify_required_tools

tab=$'\t'
pair_count=0
if [ -n "$pairs_manifest" ]; then
  if ! is_plain_file "$pairs_manifest"; then
    infra_error "pairs-manifest"
  fi
  { exec 7< "$pairs_manifest"; } 2>/dev/null \
    || infra_error "pairs-manifest-open"
  pairs_fd_path=$(fd_reference 7) || infra_error "pairs-manifest-open"
  [ -f "$pairs_fd_path" ] && [ "$pairs_manifest" -ef "$pairs_fd_path" ] \
    || infra_error "pairs-manifest-open"
  is_safe_relative_path "$pairs_manifest" \
    || infra_error "pairs-manifest-open"
  pair_seen="$temp_root/pair-seen"
  : > "$pair_seen" || infra_error "private-temp-write"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in *$'\r') line=${line%$'\r'} ;; esac
    case "$line" in
      '') continue ;;
      '#'*"$tab"*) record_violation; continue ;;
      '#'*) continue ;;
    esac
    case "$line" in
      *"$tab"*) ;;
      *) record_violation; continue ;;
    esac
    source_path=${line%%"$tab"*}
    release_path=${line#*"$tab"}
    case "$release_path" in
      *"$tab"*) record_violation; continue ;;
    esac
    if ! is_safe_relative_path "$source_path" \
        || ! is_safe_relative_path "$release_path"; then
      record_violation
      continue
    fi
    if ! mark_unique "$source_path$tab$release_path" "$pair_seen"; then
      record_violation
      continue
    fi
    pair_count=$((pair_count + 1))
    if [ "$(fold_path "$source_path")" = "$(fold_path "$release_path")" ]; then
      record_violation
      continue
    fi
    if ! is_plain_file "$source_path" || ! is_plain_file "$release_path"; then
      record_violation
      continue
    fi
    if [ "$source_path" -ef "$release_path" ]; then
      record_violation
      continue
    fi
    if ! cmp -s "$source_path" "$release_path" >/dev/null 2>&1; then
      record_violation
    fi
  done <&7
  exec 7<&-
fi

vendor_count=0
if [ "$vendor_option_count" -eq 3 ]; then
  is_plain_file "$vendor_manifest" || infra_error "vendor-manifest"
  { exec 8< "$vendor_manifest"; } 2>/dev/null \
    || infra_error "vendor-manifest-open"
  vendor_fd_path=$(fd_reference 8) || infra_error "vendor-manifest-open"
  [ -f "$vendor_fd_path" ] && [ "$vendor_manifest" -ef "$vendor_fd_path" ] \
    || infra_error "vendor-manifest-open"
  is_safe_relative_path "$vendor_manifest" \
    || infra_error "vendor-manifest-open"
  is_plain_directory "$vendor_source" || infra_error "vendor-source"
  is_plain_directory "$vendor_release" || infra_error "vendor-release"
  folded_vendor_source=$(fold_path "$vendor_source")
  folded_vendor_release=$(fold_path "$vendor_release")
  if [ "$folded_vendor_source" = "$folded_vendor_release" ]; then
    record_violation
  else
    case "$folded_vendor_release/" in
      "$folded_vendor_source/"*) record_violation ;;
    esac
    case "$folded_vendor_source/" in
      "$folded_vendor_release/"*) record_violation ;;
    esac
  fi

  vendor_seen="$temp_root/vendor-seen"
  vendor_paths="$temp_root/vendor-paths"
  source_paths="$temp_root/source-paths"
  release_paths="$temp_root/release-paths"
  : > "$vendor_seen" || infra_error "private-temp-write"
  : > "$vendor_paths" || infra_error "private-temp-write"
  : > "$source_paths" || infra_error "private-temp-write"
  : > "$release_paths" || infra_error "private-temp-write"

  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in *$'\r') line=${line%$'\r'} ;; esac
    case "$line" in
      '') continue ;;
      '#'*"$tab"*) record_violation; continue ;;
      '#'*) continue ;;
    esac
    case "$line" in
      *"$tab"*) ;;
      *) record_violation; continue ;;
    esac
    expected_digest=${line%%"$tab"*}
    relative_path=${line#*"$tab"}
    case "$relative_path" in
      *"$tab"*) record_violation; continue ;;
    esac
    case "$expected_digest" in
      *[!0-9a-f]*) record_violation; continue ;;
    esac
    if [ "${#expected_digest}" -ne 64 ] \
        || ! is_safe_relative_path "$relative_path"; then
      record_violation
      continue
    fi
    if ! mark_unique "$relative_path" "$vendor_seen"; then
      record_violation
      continue
    fi
    printf '%s\n' "$relative_path" >> "$vendor_paths" \
      || infra_error "private-temp-write"
    vendor_count=$((vendor_count + 1))
    source_file="$vendor_source/$relative_path"
    release_file="$vendor_release/$relative_path"
    if ! is_plain_file "$source_file" || ! is_plain_file "$release_file"; then
      record_violation
      continue
    fi
    if [ "$source_file" -ef "$release_file" ]; then
      record_violation
      continue
    fi
    actual_digest=$(hash_file "$source_file")
    [ "$actual_digest" = "$expected_digest" ] || record_violation
    cmp -s "$source_file" "$release_file" >/dev/null 2>&1 || record_violation
  done <&8
  exec 8<&-

  for inventory_spec in \
      "$vendor_source$tab$source_paths" \
      "$vendor_release$tab$release_paths"; do
    inventory_root=${inventory_spec%%"$tab"*}
    inventory_output=${inventory_spec#*"$tab"}
    find_output="$temp_root/find-output"
    find "$inventory_root" -mindepth 1 -print0 > "$find_output" 2>/dev/null \
      || infra_error "vendor-inventory"
    while IFS= read -r -d '' inventory_entry; do
      relative_entry=${inventory_entry#"$inventory_root"/}
      if ! is_safe_relative_path "$relative_entry"; then
        record_violation
        continue
      fi
      if [ -L "$inventory_entry" ]; then
        record_violation
      elif [ -f "$inventory_entry" ]; then
        printf '%s\n' "$relative_entry" >> "$inventory_output" \
          || infra_error "private-temp-write"
      elif [ ! -d "$inventory_entry" ]; then
        record_violation
      fi
    done < "$find_output"
  done

  vendor_sorted="$temp_root/vendor-sorted"
  source_sorted="$temp_root/source-sorted"
  release_sorted="$temp_root/release-sorted"
  sort "$vendor_paths" > "$vendor_sorted" 2>/dev/null \
    || infra_error "inventory-sort"
  sort "$source_paths" > "$source_sorted" 2>/dev/null \
    || infra_error "inventory-sort"
  sort "$release_paths" > "$release_sorted" 2>/dev/null \
    || infra_error "inventory-sort"
  cmp -s "$vendor_sorted" "$source_sorted" >/dev/null 2>&1 || record_violation
  cmp -s "$vendor_sorted" "$release_sorted" >/dev/null 2>&1 || record_violation
  [ "$vendor_count" -gt 0 ] || record_violation
fi

[ "$pair_count" -gt 0 ] || [ "$vendor_count" -gt 0 ] \
  || record_violation

if [ "$violations" -ne 0 ]; then
  printf 'release-parity: FAIL violations=%s\n' "$violations" >&2
  exit 1
fi

printf 'release-parity: PASS pairs=%s vendor=%s\n' "$pair_count" "$vendor_count"
