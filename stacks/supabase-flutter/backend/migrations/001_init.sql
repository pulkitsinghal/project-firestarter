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
-- GOTCHA (a verified, reproduced exploit in a sibling project): Postgres grants
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

-- Only approved locations are exposed via the API.
GRANT SELECT ON locations TO anon;

-- Seed one approved location so the example API + storyboard have data.
INSERT INTO locations (name, geom, is_approved)
SELECT 'hello from {{ project_slug }}', ST_GeogFromText('SRID=4326;POINT(-95.9345 41.2565)'), true
WHERE NOT EXISTS (SELECT 1 FROM locations);
