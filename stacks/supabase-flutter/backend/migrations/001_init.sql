-- 001_init.sql — {{ project_name }} initial schema (PostGIS).
-- Forward-only and idempotent: safe to re-run. Never edit an applied migration
-- except for provably idempotent hardening; new behaviour = new numbered file.

CREATE EXTENSION IF NOT EXISTS postgis;

-- PostgREST exposes tables to the `anon` role. Create it if missing.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
END $$;

-- ── Security: deny-by-default for functions (RPCs) ───────────────────────────
-- GOTCHA (a real exposure pattern, observed in practice): Postgres grants
-- EXECUTE on every function to PUBLIC by default, and PostgREST exposes any
-- function the `anon`/PUBLIC role can execute as an UNAUTHENTICATED
-- POST /rpc/<name>. So a lone `REVOKE ... FROM anon` is a no-op — PUBLIC still
-- holds EXECUTE, and an anonymous caller can invoke your internal RPCs. Strip
-- that default grant so a future function is NOT reachable until you opt it in.
--
-- Two details that both bite (verified on PG16):
--   * Use the GLOBAL form below — NOT `... IN SCHEMA public ...`, which does
--     NOT suppress the built-in PUBLIC default and silently leaves RPCs open.
--   * `ALTER DEFAULT PRIVILEGES` only affects functions created AFTER this
--     line, so the PostGIS functions from `CREATE EXTENSION` above keep their
--     grants and the anonymous read path still works. Do NOT `REVOKE ... ON ALL
--     FUNCTIONS IN SCHEMA public` — that strips PostGIS's own grants too.
--
-- To expose one specific RPC to anonymous callers, grant it explicitly:
--     GRANT EXECUTE ON FUNCTION my_public_rpc(args) TO anon;
-- Keep internal/admin functions ungranted. For a privileged operation an anon
-- flow legitimately needs, wrap it in a SECURITY DEFINER function owned by a
-- privileged role and grant EXECUTE only on that wrapper.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE IF NOT EXISTS locations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         TEXT NOT NULL,
    geom         geography(Point, 4326) NOT NULL,
    is_approved  BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Security: deny-by-default for tables (RLS) ───────────────────────────────
-- GOTCHA (the table-level analogue of the function grant above; Supabase advisor
-- `rls_disabled_in_public`): PostgREST + Supabase Cloud grant anon/authenticated
-- blanket access to public tables by default, so a `GRANT SELECT … TO anon` (or,
-- on Cloud, no grant at all) exposes EVERY row of the table — not just the ones
-- you meant to publish — until Row-Level Security is turned on. Enabling RLS
-- flips the table to deny-all; a permissive policy then re-opens exactly the rows
-- the anon client is allowed to read. `backend/security/check_rls_enabled.sh`
-- (CI: rls-guard.yml) fails if any public app table ships RLS-off and unlisted.
--
-- Here: only *approved* locations should be public, so the SELECT policy filters
-- on is_approved. The GRANT is still required — RLS narrows an existing grant, it
-- does not replace it. Internal tables that no anon flow reads directly should
-- get RLS with NO policy (deny-all); their reader/writer RPCs run SECURITY
-- DEFINER and bypass RLS.
ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON locations TO anon;
DROP POLICY IF EXISTS locations_anon_select ON locations;
CREATE POLICY locations_anon_select ON locations
    FOR SELECT TO anon
    USING (is_approved);

-- Seed one approved location so the example API + storyboard have data.
INSERT INTO locations (name, geom, is_approved)
SELECT 'hello from {{ project_slug }}', ST_GeogFromText('SRID=4326;POINT(-95.9345 41.2565)'), true
WHERE NOT EXISTS (SELECT 1 FROM locations);
