#!/bin/bash
set -euo pipefail

prototype_root=$(cd "$(dirname "$0")/.." && pwd)
preflight="$prototype_root/scripts/verify-permission-identity.sh"
fixture_root=$(/usr/bin/mktemp -d)
trap '/bin/rm -rf "$fixture_root"' EXIT

fake_codesign="$fixture_root/codesign"
fake_spctl="$fixture_root/spctl"
fake_plist_buddy="$fixture_root/PlistBuddy"

cat >"$fake_codesign" <<'EOF'
#!/bin/bash
set -euo pipefail
if [[ "$1 $2 $3" == "--verify --deep --strict" ]]; then
  [[ -f "$4/SIGNATURE_VALID" ]]
  exit
fi
if [[ "$1 $2" == "--display -r" ]]; then
  cp "$4/DESIGNATED_REQUIREMENT" "$3"
  exit
fi
if [[ "$1 $2 $3" == "--verify --strict -R" ]]; then
  cmp -s "$4" "$5/ACCEPTED_REQUIREMENT"
  exit
fi
exit 2
EOF

cat >"$fake_spctl" <<'EOF'
#!/bin/bash
set -euo pipefail
[[ "$1 $2 $3" == "--assess --type execute" ]]
[[ -f "$4/GATEKEEPER_ACCEPTED" ]]
EOF

cat >"$fake_plist_buddy" <<'EOF'
#!/bin/bash
set -euo pipefail
key=${2#Print :}
awk -F= -v key="$key" '$1 == key { print substr($0, length(key) + 2); found=1 } END { exit !found }' "$3"
EOF

chmod +x "$fake_codesign" "$fake_spctl" "$fake_plist_buddy"

make_app() {
  local path=$1
  local bundle_id=$2
  local build=$3
  local requirement=$4
  mkdir -p "$path/Contents/MacOS" "$path/Contents/Resources"
  printf '%s\n' \
    "CFBundleIdentifier=$bundle_id" \
    "CFBundleExecutable=Operations Floater" \
    "CFBundleVersion=$build" \
    >"$path/Contents/Info.plist"
  printf '#!/bin/bash\nexit 0\n' >"$path/Contents/MacOS/Operations Floater"
  chmod +x "$path/Contents/MacOS/Operations Floater"
  : >"$path/Contents/Resources/Assets.car"
  : >"$path/SIGNATURE_VALID"
  : >"$path/GATEKEEPER_ACCEPTED"
  printf '%s\n' "$requirement" >"$path/DESIGNATED_REQUIREMENT"
  printf '%s\n' "$requirement" >"$path/ACCEPTED_REQUIREMENT"
}

run_preflight() {
  CODESIGN_BIN="$fake_codesign" \
    SPCTL_BIN="$fake_spctl" \
    PLIST_BUDDY_BIN="$fake_plist_buddy" \
    "$preflight" "$@"
}

bundle_id=com.owner.operationsfloater
installed="$fixture_root/Installed.app"
candidate="$fixture_root/Candidate.app"
make_app "$installed" "$bundle_id" 7 'identifier com.owner.operationsfloater and anchor owner'
make_app "$candidate" "$bundle_id" 8 'identifier com.owner.operationsfloater and anchor owner'

run_preflight \
  --candidate "$candidate" \
  --installed "$installed" \
  --expected-bundle-id "$bundle_id" \
  | /usr/bin/grep -q 'mutually requirement-compatible'

first_install="$fixture_root/FirstInstall.app"
make_app "$first_install" "$bundle_id" 1 'identifier com.owner.operationsfloater and anchor owner'
run_preflight \
  --candidate "$first_install" \
  --expected-bundle-id "$bundle_id" \
  | /usr/bin/grep -q 'user grants Input Monitoring once'

incompatible="$fixture_root/Incompatible.app"
make_app "$incompatible" "$bundle_id" 9 'identifier com.owner.operationsfloater and anchor different-owner'
if run_preflight \
  --candidate "$incompatible" \
  --installed "$installed" \
  --expected-bundle-id "$bundle_id" \
  >/dev/null 2>&1
then
  printf 'expected incompatible designated requirement to fail\n' >&2
  exit 1
fi

helper_candidate="$fixture_root/HelperCandidate.app"
make_app "$helper_candidate" "$bundle_id" 9 'identifier com.owner.operationsfloater and anchor owner'
mkdir -p "$helper_candidate/Contents/Library/LaunchAgents"
: >"$helper_candidate/Contents/Library/LaunchAgents/com.owner.unexpected.plist"
if run_preflight \
  --candidate "$helper_candidate" \
  --expected-bundle-id "$bundle_id" \
  >/dev/null 2>&1
then
  printf 'expected unexpected helper to fail\n' >&2
  exit 1
fi

if run_preflight \
  --candidate "$candidate" \
  --expected-bundle-id com.example.operationsfloater \
  >/dev/null 2>&1
then
  printf 'expected placeholder release identifier to fail\n' >&2
  exit 1
fi

printf 'permission-identity synthetic preflight: PASS (4 cases)\n'
