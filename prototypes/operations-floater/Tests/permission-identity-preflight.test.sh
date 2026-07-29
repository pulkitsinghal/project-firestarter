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
if [[ "$1 $2" == "--display --verbose=4" ]]; then
  cat "$3/SIGNATURE_REPORT" >&2
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
    "CFBundleIconName=AppIcon" \
    >"$path/Contents/Info.plist"
  printf '#!/bin/bash\nexit 0\n' >"$path/Contents/MacOS/Operations Floater"
  chmod +x "$path/Contents/MacOS/Operations Floater"
  : >"$path/Contents/Resources/Assets.car"
  : >"$path/SIGNATURE_VALID"
  : >"$path/GATEKEEPER_ACCEPTED"
  printf '%s\n' "$requirement" >"$path/DESIGNATED_REQUIREMENT"
  printf '%s\n' "$requirement" >"$path/ACCEPTED_REQUIREMENT"
  printf '%s\n' "Authority=Developer ID Application" "TeamIdentifier=TEAMABC123" \
    >"$path/SIGNATURE_REPORT"
}

run_preflight() {
  CODESIGN_BIN="$fake_codesign" \
    SPCTL_BIN="$fake_spctl" \
    PLIST_BUDDY_BIN="$fake_plist_buddy" \
    "$preflight" "$@"
}

bundle_id=com.owner.operationsfloater
team_id=TEAMABC123
installed="$fixture_root/Installed.app"
candidate="$fixture_root/Candidate.app"
make_app "$installed" "$bundle_id" 7 'identifier "com.owner.operationsfloater" and anchor owner'
make_app "$candidate" "$bundle_id" 8 'identifier "com.owner.operationsfloater" and anchor owner'

run_preflight \
  --candidate "$candidate" \
  --installed "$installed" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  | /usr/bin/grep -q 'mutually requirement-compatible'

first_install="$fixture_root/FirstInstall.app"
make_app "$first_install" "$bundle_id" 1 'identifier "com.owner.operationsfloater" and anchor owner'
run_preflight \
  --candidate "$first_install" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  | /usr/bin/grep -q 'user grants Input Monitoring once'

incompatible="$fixture_root/Incompatible.app"
make_app "$incompatible" "$bundle_id" 9 'identifier "com.owner.operationsfloater" and anchor different-owner'
if run_preflight \
  --candidate "$incompatible" \
  --installed "$installed" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  >/dev/null 2>&1
then
  printf 'expected incompatible designated requirement to fail\n' >&2
  exit 1
fi

helper_candidate="$fixture_root/HelperCandidate.app"
make_app "$helper_candidate" "$bundle_id" 9 'identifier "com.owner.operationsfloater" and anchor owner'
mkdir -p "$helper_candidate/Contents/XPCServices/Unexpected.xpc/Contents/MacOS"
: >"$helper_candidate/Contents/XPCServices/Unexpected.xpc/Contents/MacOS/Unexpected"
if run_preflight \
  --candidate "$helper_candidate" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  >/dev/null 2>&1
then
  printf 'expected unexpected helper to fail\n' >&2
  exit 1
fi

if run_preflight \
  --candidate "$candidate" \
  --expected-bundle-id com.example.operationsfloater \
  --expected-team-id "$team_id" \
  >/dev/null 2>&1
then
  printf 'expected placeholder release identifier to fail\n' >&2
  exit 1
fi

adhoc_candidate="$fixture_root/AdHocCandidate.app"
make_app "$adhoc_candidate" "$bundle_id" 10 "designated => cdhash H\"synthetic\""
printf '%s\n' "Signature=adhoc" "TeamIdentifier=not set" \
  >"$adhoc_candidate/SIGNATURE_REPORT"
if run_preflight \
  --candidate "$adhoc_candidate" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  >/dev/null 2>&1
then
  printf 'expected ad-hoc identity to fail\n' >&2
  exit 1
fi

wrong_team_candidate="$fixture_root/WrongTeamCandidate.app"
make_app \
  "$wrong_team_candidate" \
  "$bundle_id" \
  10 \
  'identifier "com.owner.operationsfloater" and anchor owner'
printf '%s\n' "Authority=Developer ID Application" "TeamIdentifier=OTHERTEAM9" \
  >"$wrong_team_candidate/SIGNATURE_REPORT"
if run_preflight \
  --candidate "$wrong_team_candidate" \
  --expected-bundle-id "$bundle_id" \
  --expected-team-id "$team_id" \
  >/dev/null 2>&1
then
  printf 'expected wrong Team Identifier to fail\n' >&2
  exit 1
fi

printf 'permission-identity synthetic preflight: PASS (7 cases)\n'
