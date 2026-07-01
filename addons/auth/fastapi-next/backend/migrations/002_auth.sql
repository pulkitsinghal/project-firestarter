-- 002_auth.sql — {{ project_name }} durable auth store (auth add-on).
-- Forward-only and idempotent. Applied only when the project was stamped with
-- include_auth=yes. Backs PostgresAuthStore (set AUTH_STORE=postgres); the
-- default in-memory store needs none of this.

CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT,
    phone        TEXT,
    display_name TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One account per contact (partial: NULLs don't collide).
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_phone ON users (phone) WHERE phone IS NOT NULL;

CREATE TABLE IF NOT EXISTS auth_identities (
    provider TEXT NOT NULL,
    subject  TEXT NOT NULL,
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (provider, subject)
);

-- One active challenge per identifier (upsert on re-request).
CREATE TABLE IF NOT EXISTS auth_otp (
    identifier TEXT PRIMARY KEY,
    channel    TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id  TEXT,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS device_links (
    device_id TEXT PRIMARY KEY,
    user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
);

-- Rolling rate-limit / brute-force counter (one row per hit; pruned by window).
CREATE TABLE IF NOT EXISTS auth_rate_hits (
    bucket TEXT NOT NULL,
    hit_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_rate_hits_bucket_time
    ON auth_rate_hits (bucket, hit_at);
