# In-app bug reporting (optional add-on)

Closes the loop between a user hitting a bug and a fixable GitHub issue, for
{{ project_name }}. A user who can't describe a bug just taps **Report a bug** —
the app captures a breadcrumb trail + a state snapshot (+ optionally a screenshot)
and files it; a server-side script turns open reports into GitHub issues.

Enabled at generation time with `include_bug_report=yes` (supabase-flutter only).

```
in-app  →  report_bug RPC (anon)  →  public.bug_reports (JSONB)
                                          │
        pull-bug-reports.sh (postgres) ───┘ →  gh issue create  →  status='triaged'
```

## The loop

1. **Capture (client).** `app/lib/bug_report/` — a global `bugTrail` ring buffer
   (fed by `BugTrailObserver`, plus your own `bugTrail.add(...)` calls at key
   actions), a **`ScreenshotBoundary`** that snapshots the current screen to a
   base64 PNG (dependency-free — a keyed `RepaintBoundary`, no `screenshot`
   package), and a `BugReportSheet` that POSTs to the `report_bug` RPC. No extra
   packages: it uses `dart:io` HttpClient against PostgREST's anon role.
2. **Store (DB).** `backend/migrations/002_bug_reports.sql` — a `bug_reports`
   table plus two RPCs. Security mirrors `001_init.sql`'s deny-by-default posture:
   RLS on with **no policies** (no direct table access), `report_bug` granted to
   `anon` (device-keyed), `get_open_bug_reports` granted to `service_role` only.
3. **Triage (server).** `bash backend/scripts/pull-bug-reports.sh` reads new
   reports and files each as a GitHub issue (`gh`), then flips it to `triaged`
   (idempotent). `DRY_RUN=1 bash backend/scripts/pull-bug-reports.sh` prints
   instead. The GitHub token stays server-side; the issue body is formatted in
   SQL, so it needs only containerized `psql` + host `gh` (no host language SDK).

## Configuration

- **API base URL:** the client defaults to `http://localhost:{{ port_api }}`.
  Override at build time: `flutter run --dart-define=API_BASE=https://api.example.com`.
- **Device id:** a random v4 per launch in this skeleton. Persist it (e.g.
  `shared_preferences`) if you want a stable id across sessions.

## Screenshots

Built in and dependency-free. `main.dart` wraps the screen in a
`ScreenshotBoundary`; `openBugReport` captures it *before* the sheet opens (so you
grab the screen the user was on), and the sheet shows a thumbnail + an attach
toggle. Capture is best-effort — a null shot just means "no screenshot", never an
error. To make more of the app capturable, wrap the relevant subtree in a
`ScreenshotBoundary` (or move it up to your root scaffold).

## Extending it

- **Richer snapshot:** pass your own map to `submitBugReport(snapshot: …)` — route,
  feature flags, the last network call, whatever makes the bug diagnosable.
- **Hosted Supabase:** call `get_open_bug_reports` via the `service_role` REST
  endpoint instead of `psql` (it's granted to `service_role` only).
