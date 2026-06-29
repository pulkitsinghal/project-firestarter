-- 001_init.sql — {{ project_name }} initial schema.
-- Forward-only and idempotent: safe to re-run. Never edit an applied migration
-- except for provably idempotent hardening; new behaviour = new numbered file.

-- Uncomment if you need vector search (the image ships the extension):
-- CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS items (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed one row so the example endpoint and storyboard have something to show.
INSERT INTO items (name)
SELECT 'hello from {{ project_slug }}'
WHERE NOT EXISTS (SELECT 1 FROM items);
