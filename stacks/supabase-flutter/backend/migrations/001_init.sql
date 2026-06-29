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
