#!/usr/bin/env bash
# Offline repository-hygiene tripwire.
#
# The default/--staged mode scans an immutable copy of the complete Git index,
# including blob objects rather than working-tree files. --history is a superset:
# it also scans every blob reachable through refs or detached HEAD. The report is
# intentionally content-suppressed: fixed rule IDs and aggregate counts only.
# This complements gitleaks, revocation, privacy review, and incident response.

set +x
set -uo pipefail
export LC_ALL=C
export GIT_NO_LAZY_FETCH=1
export GIT_NO_REPLACE_OBJECTS=1
export GIT_OPTIONAL_LOCKS=0
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=
umask 077
shopt -s nocasematch

usage() {
  echo "usage: scripts/repo-hygiene.sh [--staged|--history]" >&2
}

infra_error() {
  echo "repo-hygiene: ERROR code=$1" >&2
  exit 2
}

scope=index
if [ "$#" -gt 1 ]; then
  usage
  exit 2
fi
if [ "$#" -eq 1 ]; then
  case "$1" in
    --staged) scope=index ;;
    --history) scope=history ;;
    *) usage; exit 2 ;;
  esac
fi

for required_tool in git grep awk mktemp mkdir cp cmp rm od head tr; do
  command -v "$required_tool" >/dev/null 2>&1 || infra_error "missing-tool"
done

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || infra_error "not-a-git-repository"
is_bare=$(git rev-parse --is-bare-repository 2>/dev/null) || infra_error "repository-state"
[ "$is_bare" = false ] || infra_error "bare-repository"
cd "$repo_root" 2>/dev/null || infra_error "unreadable-repository"

temp_base=${TMPDIR:-/tmp}
temp_root=$(mktemp -d "$temp_base/repo-hygiene.XXXXXX" 2>/dev/null) \
  || infra_error "private-temp-create"
case "$temp_root" in
  "$temp_base"/repo-hygiene.*) ;;
  *) infra_error "private-temp-path" ;;
esac
mkdir "$temp_root/counts" "$temp_root/seen" "$temp_root/covered" 2>/dev/null \
  || infra_error "private-temp-create"

cleanup() {
  cleanup_status=$?
  trap - EXIT HUP INT TERM
  case "${temp_root:-}" in
    "$temp_base"/repo-hygiene.*)
      if [ -d "$temp_root" ] && ! rm -rf "$temp_root" >/dev/null 2>&1; then
        echo "repo-hygiene: ERROR code=private-temp-cleanup" >&2
        [ "$cleanup_status" -ne 0 ] && exit "$cleanup_status"
        exit 2
      fi
      ;;
  esac
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 2' HUP INT TERM

increment_rule() {
  rule_name=$1
  increment=${2:-1}
  count_path="$temp_root/counts/$rule_name"
  current_count=0
  if [ -f "$count_path" ]; then
    IFS= read -r current_count < "$count_path" || infra_error "count-read"
  fi
  case "$current_count:$increment" in
    *[!0-9:]*) infra_error "count-state" ;;
  esac
  printf '%s\n' $((current_count + increment)) > "$count_path" \
    || infra_error "count-write"
}

# ── git-crypt / encryption awareness ────────────────────────────────────────
# repo-hygiene reads committed BLOBS, not working-tree files. When a project
# enables git-crypt (see addons/encrypted_local_areas), a tracked path declared
# with the git-crypt filter in .gitattributes is stored as ciphertext whose
# first ten bytes are the magic string "\0GITCRYPT\0". Scanning that ciphertext
# as if it were source produces false findings; silently skipping it leaves an
# undeclared blind spot. Neither is right by default, so a blob is classified
# against the declared policy: .gitattributes is the declaration, and a filtered
# path is a named class (encrypted-local) reported as covered-by-encryption —
# not clean, and not a finding. Ciphertext WITHOUT that declaration, or
# plaintext WHERE the declaration promised encryption, is a finding. The path is
# consumed internally and never emitted, so content suppression holds on every
# branch. See docs/COMPLIANCE_POSTURE.md and artifact-policy.json.
gitcrypt_magic_hex=00474954435259505400

increment_covered() {
  covered_name=$1
  covered_increment=${2:-1}
  covered_path="$temp_root/covered/$covered_name"
  current_covered=0
  if [ -f "$covered_path" ]; then
    IFS= read -r current_covered < "$covered_path" || infra_error "covered-read"
  fi
  case "$current_covered:$covered_increment" in
    *[!0-9:]*) infra_error "covered-state" ;;
  esac
  printf '%s\n' $((current_covered + covered_increment)) > "$covered_path" \
    || infra_error "covered-write"
}

path_declares_git_crypt() {
  attribute_path=$1
  [ -n "$attribute_path" ] || return 1
  attribute_line=$(git check-attr --cached filter -- "$attribute_path" 2>/dev/null) \
    || infra_error "git-check-attr"
  # Output is "<path>: filter: <value>"; <value> is a fixed word with no ": ",
  # so stripping the longest "*: " prefix yields it whatever the path contains.
  attribute_value=${attribute_line##*: }
  [ "$attribute_value" = git-crypt ]
}

blob_is_git_crypt_ciphertext() {
  ciphertext_oid=$1
  # Bounded ten-byte read: a large encrypted artifact is classified without
  # being read in full (so it never trips the oversized-blob rule). od renders
  # the bytes as hex because the magic begins with NUL, which command
  # substitution would otherwise strip. A SIGPIPE on the capped read is benign
  # here: the value is what is tested, not the pipeline's exit status.
  ciphertext_header=$(git cat-file blob "$ciphertext_oid" 2>/dev/null \
    | head -c 10 | od -An -v -tx1 -N10 2>/dev/null | tr -d '[:space:]')
  [ "$ciphertext_header" = "$gitcrypt_magic_hex" ]
}

validate_regex() {
  regex=$1
  regex_name=$2
  printf '' | grep -E -e "$regex" >/dev/null 2>&1
  regex_status=$?
  [ "$regex_status" -le 1 ] || infra_error "invalid-rule-regex-$regex_name"
}

is_forbidden_path() {
  candidate_path=$1
  candidate_base=${candidate_path##*/}

  case "$candidate_base" in
    .env.example|.env.sample|.env.template) ;;
    .env|.env.*|.envrc|git-crypt-*.key|kubeconfig|*.kubeconfig|*.tfstate|*.tfstate.*|*.log|.coverage|*.egg-info|.DS_Store|Thumbs.db|desktop.ini|*.swp|*.swo|*~) return 0 ;;
  esac
  case "$candidate_path" in
    *.tsbuildinfo|*.har) return 0 ;;
  esac
  if [[ "$candidate_path" =~ (^|/)(node_modules|build|out|dist|coverage|htmlcov|test-results|playwright-report|\.next|\.turbo|\.pnpm-store|\.wrangler|\.dart_tool|\.venv|venv|[^/]+\.egg-info|\.direnv|\.terraform|\.ruff_cache|__pycache__|\.pytest_cache|\.mypy_cache|\.cache|\.mutation-check\.lock)(/|$) ]]; then
    return 0
  fi
  if [[ "$candidate_path" =~ (^|/)((browser|chrome)[_-]?profile|\.auth)(/|$) ]]; then
    return 0
  fi
  if [[ "$candidate_path" =~ (^|/)storage[_-]?state(\.json|/|$) ]]; then
    return 0
  fi
  if [[ "$candidate_path" =~ (^|/)\.claude/(settings\.local\.json|worktrees)(/|$) ]]; then
    return 0
  fi
  if [[ "$candidate_path" =~ (^|/)(\.idea|\.vscode|\.docker-data|\.secret-vault|\.deploy|\.kube)(/|$) ]]; then
    return 0
  fi
  return 1
}

rule_names=(
  private-key-header
  credential-assignment
  authorization-value
  credentialed-url
  jwt-shaped-token
  pii-ssn
  pii-labelled-account-number
  pii-street-address
)
rule_regexes=(
  '^[[:space:]]*-----BEGIN ((RSA|EC|OPENSSH|DSA|ENCRYPTED|PGP)[[:space:]]+)?PRIVATE KEY( BLOCK)?-----[[:space:]]*$'
  "[\"']?(secret|token|password|api[_-]?key|private[_-]?key)[\"']?[[:space:]]*[:=][[:space:]]*([\"'][^\$\"'[:cntrl:]][^\"'[:cntrl:]]{15,}[\"']|[[:alnum:]][[:alnum:]_./+~=-]{23,})"
  "authorization[[:space:]]*[:=][[:space:]]*[\"']?(bearer[[:space:]]+)?[[:alnum:]_.~+/-]{16,}"
  '(https?|postgres(ql)?|mysql|redis)://[^/@[:space:]:]+:[-[:alnum:]_.~!%+;=][^/@[:space:]]{5,}@([[:alnum:]_.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]+)?'
  '(^|[^[:alnum:]_])eyJ[[:alnum:]_-]{8,}\.[[:alnum:]_-]{8,}\.[[:alnum:]_-]{8,}([^[:alnum:]_]|$)'
  '(^|[^0-9])[0-9]{3}-[0-9]{2}-[0-9]{4}([^0-9]|$)'
  '(account|acct|routing|loan|member|customer|patient)[[:space:]_#:/=.-]{0,8}[0-9]{8,20}'
  '(^|[^[:alnum:]])[0-9]{1,6}[[:space:]]+([[:alpha:]]+[[:space:]]+){1,5}(street|st|road|rd|avenue|ave|way|lane|ln|drive|dr|boulevard|blvd)([^[:alnum:]]|$)'
)
rule_exact_filter=(no yes yes yes no no no no)
exact_credential_allow_regex="^(https?://user:secret@(([[:alnum:]-]+\.)*(example\.(com|org|net)|[[:alnum:]-]+\.(test|example|invalid))|localhost|127\.0\.0\.1)(:[0-9]+)?|postgres(ql)?://postgres:postgres@(postgres|localhost|127\.0\.0\.1):[0-9]+|postgres(ql)?://(user|authenticator|gotrue):CHANGE_ME@managed-postgres:[0-9]+|[\"']?(secret|token|password|api[_-]?key|private[_-]?key)[\"']?[[:space:]]*[:=][[:space:]]*[\"']CHANGE_ME(_LONG_RANDOM)?[\"'])$"
email_regex='[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}'
scp_transport_regex='(^|[^[:alnum:]._%+-])git@[[:alnum:].-]+\.[[:alpha:]]{2,}:[[:alnum:]_.~-]+/[[:alnum:]_./~-]+($|[^[:alnum:]_./~-])'

[ "${#rule_names[@]}" -eq "${#rule_regexes[@]}" ] \
  && [ "${#rule_names[@]}" -eq "${#rule_exact_filter[@]}" ] \
  || infra_error "rule-table"

rule_index=0
while [ "$rule_index" -lt "${#rule_names[@]}" ]; do
  validate_regex "${rule_regexes[$rule_index]}" "${rule_names[$rule_index]}"
  rule_index=$((rule_index + 1))
done
validate_regex "$email_regex" "email"
validate_regex "$scp_transport_regex" "scp-transport"
validate_regex "$exact_credential_allow_regex" "exact-credential-allow"

count_non_synthetic_emails() {
  awk '
    {
      email = tolower($0)
      if (email ~ /@([[:alnum:]-]+\.)*example\.(com|org|net)$/) next
      if (email ~ /\.(test|example|invalid)$/) next
      count++
    }
    END { print count + 0 }
  '
}

count_non_synthetic_scp_transports() {
  awk '
    {
      email = tolower($0)
      sub(/^[^g]*/, "", email)
      sub(/:.*/, "", email)
      if (email ~ /@([[:alnum:]-]+\.)*example\.(com|org|net)$/) next
      if (email ~ /\.(test|example|invalid)$/) next
      count++
    }
    END { print count + 0 }
  '
}

scan_blob() {
  blob_oid=$1
  rule_prefix=$2
  blob_path=${3:-}
  case "$blob_oid" in
    ''|*[!0-9a-fA-F]*) infra_error "malformed-object-id" ;;
  esac

  object_type=$(git cat-file -t "$blob_oid" 2>/dev/null) \
    || infra_error "missing-object"
  [ "$object_type" = blob ] || infra_error "non-blob-object"

  # Encryption disposition depends on the PATH (its .gitattributes declaration)
  # and the CONTENT (whether the blob is git-crypt ciphertext), so it is decided
  # per path, before the content-based dedup below — two paths can share one
  # blob oid yet differ in whether they are declared encrypted. A pathless blob
  # (a ref pointing straight at a blob object) has no declaration to resolve and
  # falls through to the ordinary scan.
  if [ -n "$blob_path" ]; then
    if blob_is_git_crypt_ciphertext "$blob_oid"; then
      if path_declares_git_crypt "$blob_path"; then
        increment_covered "${rule_prefix}covered-by-encryption"
      else
        increment_rule "${rule_prefix}encrypted-path-not-declared"
      fi
      return 0
    elif path_declares_git_crypt "$blob_path"; then
      increment_rule "${rule_prefix}plaintext-at-encrypted-path"
      # Fall through: the exposed plaintext is also shape-scanned below.
    fi
  fi

  [ ! -e "$temp_root/seen/$blob_oid" ] || return 0
  : > "$temp_root/seen/$blob_oid" || infra_error "seen-state-write"

  blob_size=$(git cat-file -s "$blob_oid" 2>/dev/null) \
    || infra_error "missing-object"
  case "$blob_size" in
    ''|*[!0-9]*) infra_error "object-size" ;;
  esac
  if [ "$blob_size" -gt 4194304 ]; then
    increment_rule "${rule_prefix}oversized-blob"
    return 0
  fi

  blob_file="$temp_root/blob"
  git cat-file blob "$blob_oid" > "$blob_file" 2>/dev/null \
    || infra_error "object-read"

  rule_index=0
  while [ "$rule_index" -lt "${#rule_names[@]}" ]; do
    rule_match_file="$temp_root/rule-matches"
    grep -a -i -o -E -e "${rule_regexes[$rule_index]}" "$blob_file" \
      > "$rule_match_file" 2>/dev/null
    match_status=$?
    case "$match_status" in
      0)
        if [ "${rule_exact_filter[$rule_index]}" = yes ]; then
          grep -a -i -q -v -E -e "$exact_credential_allow_regex" \
            "$rule_match_file" 2>/dev/null
          filtered_status=$?
          case "$filtered_status" in
            0) increment_rule "${rule_prefix}${rule_names[$rule_index]}" ;;
            1) ;;
            *) infra_error "content-filter" ;;
          esac
        else
          increment_rule "${rule_prefix}${rule_names[$rule_index]}"
        fi
        ;;
      1) ;;
      *) infra_error "content-match" ;;
    esac
    rm -f "$rule_match_file" >/dev/null 2>&1 \
      || infra_error "private-temp-clean"
    rule_index=$((rule_index + 1))
  done

  email_matches=$(grep -a -i -o -E -e "$email_regex" "$blob_file" 2>/dev/null)
  email_status=$?
  case "$email_status" in
    0)
      email_count=$(printf '%s\n' "$email_matches" | count_non_synthetic_emails)
      scp_transport_matches=$(grep -a -i -o -E -e "$scp_transport_regex" "$blob_file" 2>/dev/null)
      scp_transport_status=$?
      case "$scp_transport_status" in
        0)
          scp_transport_count=$(printf '%s\n' "$scp_transport_matches" | count_non_synthetic_scp_transports)
          ;;
        1) scp_transport_count=0 ;;
        *) unset email_matches scp_transport_matches; infra_error "scp-transport-match" ;;
      esac
      unset scp_transport_matches
      [ "$scp_transport_count" -le "$email_count" ] || infra_error "scp-transport-count"
      email_count=$((email_count - scp_transport_count))
      [ "$email_count" -eq 0 ] || increment_rule "${rule_prefix}non-synthetic-email" "$email_count"
      unset email_matches
      ;;
    1) ;;
    *) unset email_matches; infra_error "email-match" ;;
  esac
  rm -f "$blob_file" >/dev/null 2>&1 || infra_error "private-temp-clean"
}

snapshot_index() {
  actual_index=$(git rev-parse --git-path index 2>/dev/null) \
    || infra_error "git-index-path"
  snapshot_index_path="$temp_root/index"
  if [ -f "$actual_index" ]; then
    index_initial_state=present
    cp "$actual_index" "$snapshot_index_path" 2>/dev/null \
      || infra_error "git-index-snapshot"
    snapshot_index_hash=$(git hash-object --no-filters "$snapshot_index_path" 2>/dev/null) \
      || infra_error "git-index-snapshot"
  else
    index_initial_state=missing
    GIT_INDEX_FILE="$snapshot_index_path" git read-tree --empty >/dev/null 2>&1 \
      || infra_error "git-index-snapshot"
    snapshot_index_hash=missing
  fi
  export GIT_INDEX_FILE="$snapshot_index_path"
}

verify_index_unchanged() {
  if [ "$index_initial_state" = missing ]; then
    [ ! -f "$actual_index" ] || infra_error "index-changed-during-scan"
    return 0
  fi
  [ -f "$actual_index" ] || infra_error "index-changed-during-scan"
  current_index_hash=$(git hash-object --no-filters "$actual_index" 2>/dev/null) \
    || infra_error "index-changed-during-scan"
  [ "$current_index_hash" = "$snapshot_index_hash" ] \
    || infra_error "index-changed-during-scan"
}

scan_index() {
  rule_prefix=$1
  index_manifest="$temp_root/index-manifest"
  git ls-files --stage -z > "$index_manifest" 2>/dev/null \
    || infra_error "git-index-read"
  while IFS= read -r -d '' index_record; do
    case "$index_record" in
      *$'\t'*) ;;
      *) infra_error "malformed-index-entry" ;;
    esac
    index_meta=${index_record%%$'\t'*}
    index_path=${index_record#*$'\t'}
    index_extra=
    IFS=' ' read -r index_mode index_oid index_stage index_extra <<< "$index_meta"
    [ -n "$index_mode" ] && [ -n "$index_oid" ] \
      && [ -n "$index_stage" ] && [ -z "$index_extra" ] \
      || infra_error "malformed-index-entry"
    [ "$index_stage" = 0 ] || infra_error "unmerged-index"
    if is_forbidden_path "$index_path"; then
      increment_rule "${rule_prefix}forbidden-path"
    fi
    case "$index_mode" in
      100644|100755|120000) scan_blob "$index_oid" "$rule_prefix" "$index_path" ;;
      160000) ;;
      *) infra_error "unsupported-index-mode" ;;
    esac
  done < "$index_manifest"
}

snapshot_refs() {
  refs_before="$temp_root/refs-before"
  git for-each-ref --format='%(refname) %(objectname)' > "$refs_before" 2>/dev/null \
    || infra_error "git-ref-snapshot"
  head_oid=$(git rev-parse --verify 'HEAD^{commit}' 2>/dev/null)
  head_status=$?
  case "$head_status" in
    0) printf 'HEAD %s\n' "$head_oid" >> "$refs_before" ;;
    128) printf 'HEAD unborn\n' >> "$refs_before" ;;
    *) infra_error "git-ref-snapshot" ;;
  esac
}

verify_refs_unchanged() {
  refs_after="$temp_root/refs-after"
  git for-each-ref --format='%(refname) %(objectname)' > "$refs_after" 2>/dev/null \
    || infra_error "git-ref-read"
  current_head=$(git rev-parse --verify 'HEAD^{commit}' 2>/dev/null)
  head_status=$?
  case "$head_status" in
    0) printf 'HEAD %s\n' "$current_head" >> "$refs_after" ;;
    128) printf 'HEAD unborn\n' >> "$refs_after" ;;
    *) infra_error "git-ref-read" ;;
  esac
  cmp -s "$refs_before" "$refs_after" || infra_error "refs-changed-during-scan"
}

scan_history() {
  revision_starts="$temp_root/revision-starts"
  : > "$revision_starts" || infra_error "git-ref-parse"

  while IFS=' ' read -r ref_label ref_oid ref_extra; do
    [ -n "$ref_label" ] && [ -n "$ref_oid" ] && [ -z "${ref_extra:-}" ] \
      || infra_error "git-ref-parse"
    [ "$ref_oid" != unborn ] || continue
    case "$ref_oid" in
      *[!0-9a-fA-F]*) infra_error "malformed-ref-object" ;;
    esac
    root_oid=$ref_oid
    root_type=$(git cat-file -t "$root_oid" 2>/dev/null) \
      || infra_error "missing-ref-object"
    if [ "$root_type" = tag ]; then
      root_oid=$(git rev-parse "$root_oid^{}" 2>/dev/null) \
        || infra_error "tag-peel"
      root_type=$(git cat-file -t "$root_oid" 2>/dev/null) \
        || infra_error "missing-ref-object"
    fi
    case "$root_type" in
      commit) printf '%s\n' "$root_oid" >> "$revision_starts" \
        || infra_error "git-ref-parse" ;;
      tree) scan_tree "$root_oid" ;;
      blob) scan_blob "$root_oid" "historical-" "" ;;
      *) infra_error "unsupported-ref-object" ;;
    esac
  done < "$refs_before"

  commits_file="$temp_root/commits"
  if [ -s "$revision_starts" ]; then
    git rev-list --stdin < "$revision_starts" > "$commits_file" 2>/dev/null \
      || infra_error "git-history-read"
  else
    : > "$commits_file"
  fi

  while IFS= read -r commit_oid; do
    [ -n "$commit_oid" ] || continue
    case "$commit_oid" in
      *[!0-9a-fA-F]*) infra_error "malformed-commit-id" ;;
    esac
    scan_tree "$commit_oid"
  done < "$commits_file"
}

scan_tree() {
  treeish_oid=$1
  case "$treeish_oid" in
    ''|*[!0-9a-fA-F]*) infra_error "malformed-treeish-id" ;;
  esac
  tree_manifest="$temp_root/tree-manifest"
  git ls-tree -r -z --full-tree "$treeish_oid" > "$tree_manifest" 2>/dev/null \
    || infra_error "git-history-tree-read"
  while IFS= read -r -d '' tree_record; do
    case "$tree_record" in
      *$'\t'*) ;;
      *) infra_error "malformed-tree-entry" ;;
    esac
    tree_meta=${tree_record%%$'\t'*}
    tree_path=${tree_record#*$'\t'}
    tree_extra=
    IFS=' ' read -r tree_mode tree_type tree_oid tree_extra <<< "$tree_meta"
    [ -n "$tree_mode" ] && [ -n "$tree_type" ] \
      && [ -n "$tree_oid" ] && [ -z "$tree_extra" ] \
      || infra_error "malformed-tree-entry"
    if is_forbidden_path "$tree_path"; then
      increment_rule "historical-forbidden-path"
    fi
    case "$tree_mode:$tree_type" in
      100644:blob|100755:blob|120000:blob) scan_blob "$tree_oid" "historical-" "$tree_path" ;;
      160000:commit) ;;
      *) infra_error "unsupported-tree-entry" ;;
    esac
  done < "$tree_manifest"
}

snapshot_index
if [ "$scope" = index ]; then
  scan_index ""
else
  shallow_state=$(git rev-parse --is-shallow-repository 2>/dev/null) \
    || infra_error "git-history-state"
  case "$shallow_state" in
    false) ;;
    true) infra_error "history-incomplete-shallow" ;;
    *) infra_error "git-history-state" ;;
  esac
  snapshot_refs
  scan_index "index-"
  scan_history
  verify_refs_unchanged
fi
verify_index_unchanged

for covered_path in "$temp_root"/covered/*; do
  [ -f "$covered_path" ] || continue
  covered_class=${covered_path##*/}
  IFS= read -r covered_count < "$covered_path" || infra_error "covered-read"
  echo "repo-hygiene: covered scope=$scope class=$covered_class paths=$covered_count" >&2
done

finding_rules=0
for count_path in "$temp_root"/counts/*; do
  [ -f "$count_path" ] || continue
  rule_name=${count_path##*/}
  IFS= read -r occurrence_count < "$count_path" || infra_error "count-read"
  echo "repo-hygiene: finding scope=$scope rule=$rule_name hits=$occurrence_count" >&2
  finding_rules=$((finding_rules + 1))
done

if [ "$finding_rules" -ne 0 ]; then
  echo "repo-hygiene: FAIL scope=$scope rules=$finding_rules" >&2
  exit 1
fi

echo "repo-hygiene: PASS scope=$scope"
