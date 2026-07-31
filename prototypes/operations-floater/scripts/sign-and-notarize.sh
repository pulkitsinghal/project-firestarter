#!/bin/bash
# Sign, notarize, staple, and verify a built Operations Floater.app for
# Developer ID (direct) distribution with the Hardened Runtime.
#
# This script is OWNER-RUN. It is intentionally free of credentials, team
# identifiers, Apple IDs, and bundle identifiers: the signing identity and the
# notary keychain profile are supplied by the owner as flags or environment
# variables. It never embeds, prints, or persists any secret.
#
# It does NOT build the app. Compile the .app on a disposable macOS account or
# CI runner first (Xcode 26.5 runs lsregister during build/archive; see
# docs/PERMISSION_AND_INSTALL_LIFECYCLE.md), then point this script at the
# resulting bundle.
#
# Chain:
#   1. codesign --options runtime (Hardened Runtime) + entitlements + secure timestamp
#   2. xcrun notarytool submit --wait
#   3. xcrun stapler staple
#   4. verify: spctl -a -vv, codesign --verify --deep --strict, stapler validate
#
# Usage:
#   scripts/sign-and-notarize.sh \
#     --app "/path/to/Operations Floater.app" \
#     --identity "Developer ID Application: Example Owner (TEAMID1234)" \
#     --notary-profile operations-floater-notary \
#     [--entitlements /path/to/OperationsFloater.entitlements] \
#     [--bundle-id com.owner.operationsfloater]
#
# Equivalent environment variables (flags win):
#   DEVELOPER_ID_APP   -> --identity
#   NOTARY_PROFILE     -> --notary-profile
#   ENTITLEMENTS       -> --entitlements
#   BUNDLE_ID          -> --bundle-id   (optional; validated, never required)
#
# The notary profile is created once by the owner (values never touch this repo):
#   xcrun notarytool store-credentials operations-floater-notary \
#     --apple-id "<apple-id>" --team-id "<TEAMID>" --password "<app-specific-password>"
#   # or, preferred, an App Store Connect API key:
#   xcrun notarytool store-credentials operations-floater-notary \
#     --key "<AuthKey_XXXX.p8>" --key-id "<KEY_ID>" --issuer "<ISSUER_UUID>"

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
default_entitlements="$script_dir/../OperationsFloater.entitlements"

usage() {
  sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

fail() {
  printf 'sign-and-notarize: FAIL: %s\n' "$*" >&2
  exit 1
}

info() {
  printf 'sign-and-notarize: %s\n' "$*"
}

app=
identity=${DEVELOPER_ID_APP:-}
notary_profile=${NOTARY_PROFILE:-}
entitlements=${ENTITLEMENTS:-$default_entitlements}
bundle_id=${BUNDLE_ID:-}

while (($#)); do
  case "$1" in
    --app)
      (($# >= 2)) || fail "--app requires a path"
      app=$2
      shift 2
      ;;
    --identity)
      (($# >= 2)) || fail "--identity requires a value"
      identity=$2
      shift 2
      ;;
    --notary-profile)
      (($# >= 2)) || fail "--notary-profile requires a value"
      notary_profile=$2
      shift 2
      ;;
    --entitlements)
      (($# >= 2)) || fail "--entitlements requires a path"
      entitlements=$2
      shift 2
      ;;
    --bundle-id)
      (($# >= 2)) || fail "--bundle-id requires a value"
      bundle_id=$2
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

# --- Preconditions ---------------------------------------------------------

[[ -n "$app" ]] || fail "--app is required (path to the built .app bundle)"
[[ -d "$app" ]] || fail "app bundle does not exist: $app"
[[ "$app" == *.app ]] || fail "app must be a .app bundle: $app"
[[ -n "$identity" ]] \
  || fail "signing identity is required (--identity or DEVELOPER_ID_APP); \
must be a 'Developer ID Application: ...' certificate in the login keychain"
[[ -n "$notary_profile" ]] \
  || fail "notary profile is required (--notary-profile or NOTARY_PROFILE); \
create it once with 'xcrun notarytool store-credentials'"
[[ -f "$entitlements" ]] || fail "entitlements file not found: $entitlements"

# Public-repo safety: refuse the disposable placeholder identifier as a release
# identity, mirroring scripts/verify-permission-identity.sh.
if [[ -n "$bundle_id" ]]; then
  case "$bundle_id" in
    com.example.*|*.example|*'*'*)
      fail "--bundle-id must be the owner-controlled release identifier, not a placeholder"
      ;;
  esac
fi

for tool in codesign ditto xcrun spctl; do
  command -v "$tool" >/dev/null 2>&1 || fail "required tool not found on PATH: $tool"
done
xcrun --find notarytool >/dev/null 2>&1 || fail "xcrun notarytool is unavailable (install Xcode command line tools)"
xcrun --find stapler >/dev/null 2>&1 || fail "xcrun stapler is unavailable (install Xcode command line tools)"

info "app:            $app"
info "identity:       $identity"
info "notary profile: $notary_profile"
info "entitlements:   $entitlements"
[[ -n "$bundle_id" ]] && info "bundle id:      $bundle_id"

# --- 1. Sign with Hardened Runtime + entitlements + secure timestamp -------
#
# This bundle embeds no frameworks, XPC services, or helper tools, so a single
# signing pass is correct. If nested code is ever added, sign it inside-out
# (deepest first) BEFORE signing the outer bundle; do not rely on --deep to sign.
info "signing (Hardened Runtime + entitlements + secure timestamp)..."
codesign \
  --force \
  --timestamp \
  --options runtime \
  --entitlements "$entitlements" \
  --sign "$identity" \
  "$app"

info "verifying local signature before notarization..."
codesign --verify --strict --verbose=2 "$app" \
  || fail "post-sign signature verification failed"

# --- 2. Notarize (submit a zip, wait for the verdict) ----------------------
#
# notarytool accepts a .zip/.pkg/.dmg, not a bare .app. Zip for submission only;
# the ticket is stapled to the .app itself in step 3.
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
zip_path="$workdir/$(basename "$app" .app).zip"

info "zipping bundle for submission..."
ditto -c -k --keepParent "$app" "$zip_path"

info "submitting to Apple notary service (this blocks until a verdict)..."
if ! xcrun notarytool submit "$zip_path" \
  --keychain-profile "$notary_profile" \
  --wait; then
  fail "notarization was not accepted; re-run 'xcrun notarytool log <submission-id> \
--keychain-profile $notary_profile' for the detailed issue list"
fi

# --- 3. Staple the ticket to the bundle ------------------------------------
info "stapling notarization ticket..."
xcrun stapler staple "$app" || fail "stapler could not attach the ticket"

# --- 4. Verify the shipped artifact ----------------------------------------
info "verifying Gatekeeper assessment (spctl)..."
spctl --assess --type execute -vv "$app" \
  || fail "Gatekeeper rejected the stapled bundle (spctl --assess)"

info "verifying signature (codesign --verify --deep --strict)..."
codesign --verify --deep --strict --verbose=2 "$app" \
  || fail "codesign deep/strict verification failed"

info "validating stapled ticket (stapler validate)..."
xcrun stapler validate "$app" || fail "stapled ticket did not validate"

info "effective entitlements on the signed bundle:"
codesign --display --entitlements - --xml "$app" 2>/dev/null || true

info "PASS: signed, notarized, stapled, and verified: $app"
