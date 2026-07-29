#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  verify-permission-identity.sh \
    --candidate /absolute/path/Operations\ Floater.app \
    --expected-bundle-id com.example.owner.operationsfloater \
    [--installed /absolute/path/Operations\ Floater.app]

Read-only preflight for a first install or update. It never signs, copies,
launches, terminates, grants/resets TCC, or changes System Settings.
EOF
}

fail() {
  printf 'permission-identity preflight: FAIL: %s\n' "$*" >&2
  exit 1
}

candidate_app=
installed_app=
expected_bundle_id=
while (($#)); do
  case "$1" in
    --candidate)
      (($# >= 2)) || fail "--candidate requires a path"
      candidate_app=$2
      shift 2
      ;;
    --installed)
      (($# >= 2)) || fail "--installed requires a path"
      installed_app=$2
      shift 2
      ;;
    --expected-bundle-id)
      (($# >= 2)) || fail "--expected-bundle-id requires a value"
      expected_bundle_id=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "$candidate_app" ]] || fail "--candidate is required"
[[ -n "$expected_bundle_id" ]] || fail "--expected-bundle-id is required"
[[ "$candidate_app" == /* ]] || fail "candidate path must be absolute"
if [[ -n "$installed_app" ]]; then
  [[ "$installed_app" == /* ]] || fail "installed path must be absolute"
fi
case "$expected_bundle_id" in
  com.example.*|*.example|*'*'*|'')
    fail "expected bundle identifier must be the owner-controlled release identifier"
    ;;
esac

codesign_bin=${CODESIGN_BIN:-/usr/bin/codesign}
spctl_bin=${SPCTL_BIN:-/usr/sbin/spctl}
plist_buddy_bin=${PLIST_BUDDY_BIN:-/usr/libexec/PlistBuddy}

plist_value() {
  local app=$1
  local key=$2
  "$plist_buddy_bin" -c "Print :$key" "$app/Contents/Info.plist" 2>/dev/null
}

reject_embedded_helpers() {
  local app=$1
  local relative
  local helper
  for relative in \
    Contents/Library/LoginItems \
    Contents/Library/LaunchAgents \
    Contents/Library/LaunchDaemons \
    Contents/Library/LaunchServices \
    Contents/Library/PrivilegedHelperTools
  do
    [[ -d "$app/$relative" ]] || continue
    helper=$(/usr/bin/find "$app/$relative" -type f -print -quit)
    [[ -z "$helper" ]] || fail "$app contains an unexpected helper at $helper"
  done
}

verify_bundle_shape() {
  local app=$1
  local label=$2
  local bundle_id
  local executable
  local ui_element

  [[ -d "$app" ]] || fail "$label app does not exist: $app"
  [[ -f "$app/Contents/Info.plist" ]] || fail "$label Info.plist is missing"
  bundle_id=$(plist_value "$app" CFBundleIdentifier) \
    || fail "$label bundle identifier is unreadable"
  [[ "$bundle_id" == "$expected_bundle_id" ]] \
    || fail "$label bundle identifier is $bundle_id, expected $expected_bundle_id"
  executable=$(plist_value "$app" CFBundleExecutable) \
    || fail "$label executable name is unreadable"
  [[ "$executable" != */* && -n "$executable" ]] \
    || fail "$label executable name is unsafe"
  [[ -x "$app/Contents/MacOS/$executable" ]] \
    || fail "$label executable is missing or not executable"
  if ui_element=$(plist_value "$app" LSUIElement); then
    case "$ui_element" in
      true|TRUE|yes|YES|1)
        fail "$label is an agent-only app and would not provide the audited Dock launcher"
        ;;
    esac
  fi
  [[ -f "$app/Contents/Resources/Assets.car" ]] \
    || fail "$label compiled application icon catalog is missing"
  reject_embedded_helpers "$app"
  "$codesign_bin" --verify --deep --strict "$app" >/dev/null 2>&1 \
    || fail "$label signature is invalid"
  "$spctl_bin" --assess --type execute "$app" >/dev/null 2>&1 \
    || fail "$label fails Gatekeeper assessment"
}

verify_bundle_shape "$candidate_app" "candidate"

temporary_directory=$(/usr/bin/mktemp -d)
trap '/bin/rm -rf "$temporary_directory"' EXIT
candidate_requirement="$temporary_directory/candidate.requirement"
"$codesign_bin" --display -r "$candidate_requirement" "$candidate_app" \
  >/dev/null 2>&1 \
  || fail "candidate designated requirement is unavailable"
[[ -s "$candidate_requirement" ]] \
  || fail "candidate designated requirement is empty"

if [[ -z "$installed_app" ]]; then
  printf '%s\n' \
    "permission-identity preflight: PASS: signed first-install candidate; user grants Input Monitoring once after installation"
  exit 0
fi

verify_bundle_shape "$installed_app" "installed"
installed_requirement="$temporary_directory/installed.requirement"
"$codesign_bin" --display -r "$installed_requirement" "$installed_app" \
  >/dev/null 2>&1 \
  || fail "installed designated requirement is unavailable"
[[ -s "$installed_requirement" ]] \
  || fail "installed designated requirement is empty"

"$codesign_bin" --verify --strict -R "$installed_requirement" "$candidate_app" \
  >/dev/null 2>&1 \
  || fail "candidate does not satisfy the installed app designated requirement"
"$codesign_bin" --verify --strict -R "$candidate_requirement" "$installed_app" \
  >/dev/null 2>&1 \
  || fail "installed app does not satisfy the candidate designated requirement"

candidate_build=$(plist_value "$candidate_app" CFBundleVersion) \
  || fail "candidate build version is unreadable"
installed_build=$(plist_value "$installed_app" CFBundleVersion) \
  || fail "installed build version is unreadable"
[[ "$candidate_build" =~ ^[0-9]+$ && "$installed_build" =~ ^[0-9]+$ ]] \
  || fail "build versions must be monotonic integers"
((candidate_build > installed_build)) \
  || fail "candidate build $candidate_build must be newer than installed build $installed_build"

printf '%s\n' \
  "permission-identity preflight: PASS: update is mutually requirement-compatible; existing TCC grants are eligible to persist"
