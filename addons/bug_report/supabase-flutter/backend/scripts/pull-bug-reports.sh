#!/usr/bin/env bash
# Pull captured bug reports and file them as GitHub issues for a human/AI to fix.
#
# The owner/AI side of the in-app bug-capture loop (migration 002_bug_reports):
#   in-app report_bug (anon, device-keyed)  ->  public.bug_reports (JSONB)
#   THIS script (DB-side, via postgres)      ->  `gh issue create`  ->  status='triaged'
#
# The GitHub token stays entirely server-side (never in the app). The markdown
# issue body is formatted in SQL (jsonb_pretty), so this needs only the
# containerized psql + host `gh` — no host language SDK (honors the template's
# no-host-toolchains rule). Idempotent on status: a filed report flips to
# 'triaged' so it isn't filed twice.
#
# Usage:
#   bash backend/scripts/pull-bug-reports.sh            # file issues
#   DRY_RUN=1 bash backend/scripts/pull-bug-reports.sh  # print, don't file
#
# Requires the local stack up (`make up`) and, to actually file, `gh` authed.
# On a hosted Supabase deploy, call get_open_bug_reports via the service_role
# REST endpoint instead of psql (it's granted to service_role only).
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=(docker compose exec -T postgres psql -U postgres -d {{ db_name }} -tA)

# id<TAB>title for every NEW report (both single-line, safe to read by field).
mapfile -t rows < <("${PSQL[@]}" -F $'\t' -c \
  "SELECT id, coalesce(nullif(title, ''), 'Bug report ' || left(id::text, 8))
   FROM public.bug_reports WHERE status = 'new' ORDER BY created_at;")

if [ "${#rows[@]}" -eq 0 ] || [ -z "${rows[0]}" ]; then
  echo "No new bug reports."
  exit 0
fi
echo "Found ${#rows[@]} new bug report(s)."

for row in "${rows[@]}"; do
  [ -z "$row" ] && continue
  rid="${row%%$'\t'*}"
  title="${row#*$'\t'}"

  bodyfile="$(mktemp)"
  # Format the whole markdown body in SQL so no host python/jq is needed.
  "${PSQL[@]}" -c "SELECT format(
      E'Captured in-app via the bug-report flow (ref \`%s\`).\n\n'
      '- **Route:** \`%s\`\n- **App version:** \`%s\`\n- **Captured:** %s\n'
      '- **Screenshot:** %s\n\n### State snapshot\n\`\`\`json\n%s\n\`\`\`\n\n'
      '### Action breadcrumbs (most recent last)\n\`\`\`json\n%s\n\`\`\`\n\n---\n'
      '_Filed by backend/scripts/pull-bug-reports.sh. When fixed, set '
      'status=''fixed'' in bug_reports._',
      id, route, app_version, created_at,
      CASE WHEN screenshot IS NOT NULL
           THEN 'in bug_reports.screenshot (base64) for this id' ELSE 'none' END,
      jsonb_pretty(snapshot), jsonb_pretty(breadcrumbs))
    FROM public.bug_reports WHERE id = '${rid}';" > "$bodyfile"

  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "── [$rid] $title"; cat "$bodyfile"; echo; rm -f "$bodyfile"; continue
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "gh not found — issue body for $rid written to $bodyfile (file it manually)"
    continue
  fi
  url="$(gh issue create --title "$title" --body-file "$bodyfile" --label bug 2>/dev/null \
        || gh issue create --title "$title" --body-file "$bodyfile")"
  echo "Filed: $url"
  "${PSQL[@]}" -c "UPDATE public.bug_reports SET status='triaged' WHERE id='${rid}';" >/dev/null
  rm -f "$bodyfile"
done
echo "Done."
