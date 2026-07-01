-- One-time bootstrap so GoTrue can run its own migrations on a FRESH volume.
-- Runs once via docker-entrypoint-initdb.d (postgres only executes these on an
-- empty data dir). Supabase's official postgres image creates the auth schema in
-- its own init scripts; our plain PostGIS image (imresamu/postgis) does not — so
-- without this, GoTrue crash-loops on first boot with "schema auth does not
-- exist" (the compose bakes ?search_path=auth into GoTrue's connection).

CREATE SCHEMA IF NOT EXISTS auth;

-- GoTrue v2.191.0's migration 011 copies versions from public.schema_migrations
-- into auth.schema_migrations with a bare INSERT, but never creates
-- public.schema_migrations itself — so on a fresh DB that INSERT fails with
-- "relation does not exist." Seed the empty table so GoTrue's migrations finish.
-- (If you bump the pinned GoTrue image, re-check whether this is still needed.)
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version text NOT NULL PRIMARY KEY
);
