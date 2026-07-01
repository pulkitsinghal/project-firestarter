-- 002_bug_reports.sql — {{ project_name }} in-app bug capture (bug_report add-on).
-- Forward-only and idempotent.
--
-- Lets a user who can't describe a bug capture the repro instead: a breadcrumb
-- trail of recent actions + a structured app-state snapshot (route, app version,
-- whatever you add) + an optional screenshot. Stored as JSONB so an AI/triager
-- can read it directly and file it as a GitHub issue (see
-- backend/scripts/pull-bug-reports.sh).
--
-- Security (mirrors the deny-by-default RPC posture in 001_init.sql):
--   * The table has RLS enabled with NO policies, so PostgREST direct table
--     access is locked out — the SECURITY DEFINER RPC is the only writer.
--   * `report_bug` is granted to `anon` (the only credential is possession of a
--     device UUID). `get_open_bug_reports` is granted to `service_role` ONLY, so
--     device ids / snapshots never leak through the anonymous API.

-- Ensure the roles this migration grants to exist (self-standing; 001 also makes anon).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.bug_reports (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id    UUID,  -- the anonymous caller's device id; no FK (auth is optional)
    status       TEXT NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new', 'triaged', 'fixed', 'wontfix')),
    title        TEXT,
    route        TEXT,
    app_version  TEXT,
    breadcrumbs  JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot     JSONB NOT NULL DEFAULT '{}'::jsonb,
    screenshot   TEXT,  -- base64 PNG, optional
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bug_reports_status_created
    ON public.bug_reports (status, created_at DESC);

ALTER TABLE public.bug_reports ENABLE ROW LEVEL SECURITY;
-- (intentionally no policies: only the SECURITY DEFINER RPC writes; no API SELECT)

-- ── report_bug: anon device-keyed writer ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.report_bug(
    p_device_id   UUID,
    p_title       TEXT,
    p_route       TEXT,
    p_app_version TEXT,
    p_breadcrumbs JSONB,
    p_snapshot    JSONB,
    p_screenshot  TEXT DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
    v_id UUID;
BEGIN
    -- Guard against oversized screenshots: drop the blob rather than reject the
    -- whole report (breadcrumbs + snapshot are the load-bearing part).
    IF p_screenshot IS NOT NULL AND length(p_screenshot) > 2000000 THEN
        p_screenshot := NULL;
    END IF;

    INSERT INTO public.bug_reports
        (device_id, title, route, app_version, breadcrumbs, snapshot, screenshot)
    VALUES
        (p_device_id, left(coalesce(p_title, ''), 200), p_route, p_app_version,
         coalesce(p_breadcrumbs, '[]'::jsonb), coalesce(p_snapshot, '{}'::jsonb),
         p_screenshot)
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

-- Explicit REVOKE-then-GRANT (don't rely on 001's default-privilege posture
-- being in effect — see the #17 lesson): strip the built-in PUBLIC EXECUTE
-- default, then grant only the intended roles.
REVOKE EXECUTE ON FUNCTION
    public.report_bug(UUID, TEXT, TEXT, TEXT, JSONB, JSONB, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    public.report_bug(UUID, TEXT, TEXT, TEXT, JSONB, JSONB, TEXT)
    TO anon, service_role;

-- ── get_open_bug_reports: owner/AI pull (service_role only) ───────────────────
-- Returns new/triaged reports for an offline triage step (the pull script formats
-- them into GitHub issues). NOT granted to anon — device ids and snapshots must
-- never be queryable through the public API.
CREATE OR REPLACE FUNCTION public.get_open_bug_reports(p_limit INT DEFAULT 50)
RETURNS SETOF public.bug_reports
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
    SELECT * FROM public.bug_reports
    WHERE status IN ('new', 'triaged')
    ORDER BY created_at DESC
    LIMIT greatest(1, least(p_limit, 500));
$$;

REVOKE EXECUTE ON FUNCTION public.get_open_bug_reports(INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_open_bug_reports(INT) TO service_role;
