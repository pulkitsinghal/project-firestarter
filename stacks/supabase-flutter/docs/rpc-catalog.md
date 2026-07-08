# RPC catalog

The contract for every PostgREST RPC {{ project_name }} exposes. PostgREST serves
a function as `POST /rpc/<name>` **only** to the roles you grant `EXECUTE` — and
this stack is deny-by-default (`backend/migrations/001_init.sql` revokes the
implicit `PUBLIC` grant, so an RPC is invisible until you opt it in). Keep this
doc in sync with the SQL; if they disagree, **the SQL wins — update this doc.**

## Conventions

- Each RPC ships in a forward-only migration (`backend/migrations/NNN_*.sql`).
- Grant intentionally: `GRANT EXECUTE ON FUNCTION my_rpc(args) TO anon;` for an
  anonymous-callable RPC; leave internal/admin functions ungranted.
- For a privileged operation an anonymous flow legitimately needs, wrap it in a
  `SECURITY DEFINER` function owned by a privileged role and grant only that
  wrapper.
- Clients call these via the Supabase Dart/JS SDK's `rpc(...)`.
- **Enforced in CI:** `anon-execute-guard.yml` runs `backend/security/check_anon_execute.sh`
  on every migration/security change and fails the build if any public function is
  `anon`-executable but not in `backend/security/anon_execute_allowlist.txt`. The
  deny-by-default posture can't silently regress — a new anon RPC must be *reviewed
  into* the allow-list (or explicitly REVOKEd).

## Catalog

_No application RPCs yet — the starter exposes only the `locations` table via
PostgREST's table API. Add an entry per RPC as you create them, using the
template below._

### `<function_name>` — entry template
- **Migration:** `backend/migrations/NNN_<topic>.sql`
- **Exposed to:** `anon` · `authenticated` · _(internal only — ungranted)_
- **Purpose:** one line.
- **Arguments:** `p_foo TYPE` — meaning · `p_bar TYPE` — meaning.
- **Returns:** the row/set shape.
- **Errors:** `RAISE EXCEPTION` message prefixes, if any (e.g. `not_found:<id>`).
- **Called by:** the client service (e.g. `services/lib/src/*.dart`).
