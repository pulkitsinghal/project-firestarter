import assert from "node:assert/strict";
import test from "node:test";

import { loadConfig } from "../../src/config.js";

const VALID_ENV = {
  SESSION_SECRET: "a-valid-session-secret-with-32-bytes",
  PUBLIC_ORIGIN: "http://localhost:3000",
};

const PRODUCTION_ENV = {
  ...VALID_ENV,
  NODE_ENV: "production",
  AUTH_MODE: "oidc",
  PUBLIC_ORIGIN: "https://notifier.example",
  REDIS_URL: "rediss://notifier-user:password@redis.example:6380/0",
  OIDC_ISSUER: "https://identity.example/",
  OIDC_AUDIENCE: "https://notifier.example/api",
  OIDC_JWKS_URL: "https://identity.example/.well-known/jwks.json",
};

test("loadConfig applies safe tutorial defaults", () => {
  const config = loadConfig(VALID_ENV);

  assert.equal(config.port, 3000);
  assert.equal(config.host, "127.0.0.1");
  assert.equal(config.redisUrl, "redis://localhost:6379");
  assert.equal(config.workerConcurrency, 4);
  assert.equal(config.taskRetentionSeconds, 86400);
  assert.equal(config.taskRateLimit, 30);
  assert.equal(config.authMode, "anonymous");
  assert.equal(config.isProduction, false);
});

test("loadConfig requires a sufficiently long session secret", () => {
  assert.throws(
    () => loadConfig({ ...VALID_ENV, SESSION_SECRET: "too-short" }),
    /at least 32 bytes/,
  );
});

test("loadConfig rejects origins with paths", () => {
  assert.throws(
    () =>
      loadConfig({
        ...VALID_ENV,
        PUBLIC_ORIGIN: "https://example.com/a/path",
      }),
    /scheme, host, and optional port/,
  );
});

test("loadConfig validates bounded worker settings", () => {
  assert.throws(
    () => loadConfig({ ...VALID_ENV, WORKER_CONCURRENCY: "0" }),
    /between 1 and 64/,
  );
  assert.throws(
    () => loadConfig({ ...VALID_ENV, TASK_DELAY_MS: "30001" }),
    /between 10 and 30000/,
  );
});

test("loadConfig rejects a non-numeric Redis database", () => {
  assert.throws(
    () => loadConfig({ ...VALID_ENV, REDIS_URL: "redis://localhost/not-a-db" }),
    /database path/,
  );
});

test("loadConfig requires HTTPS in production", () => {
  assert.throws(
    () =>
      loadConfig({
        ...PRODUCTION_ENV,
        PUBLIC_ORIGIN: "http://notifier.example",
      }),
    /must use https/,
  );
  assert.equal(loadConfig(PRODUCTION_ENV).isProduction, true);
});

test("production requires OIDC plus ACL-authenticated Redis TLS", () => {
  assert.throws(
    () => loadConfig({ ...PRODUCTION_ENV, AUTH_MODE: "anonymous" }),
    /AUTH_MODE must be oidc/,
  );
  assert.throws(
    () =>
      loadConfig({
        ...PRODUCTION_ENV,
        REDIS_URL: "redis://redis.example:6379",
      }),
    /rediss.*ACL username and password/,
  );
  assert.throws(
    () =>
      loadConfig({
        ...PRODUCTION_ENV,
        REDIS_URL: "rediss://redis.example:6380",
      }),
    /ACL username and password/,
  );
});

test("OIDC and retention settings are bounded", () => {
  const config = loadConfig({
    ...PRODUCTION_ENV,
    OIDC_ALGORITHMS: "RS256,ES256",
    OIDC_TENANT_CLAIM: "org.id",
    TASK_RETENTION_SECONDS: "7200",
    TASK_RATE_LIMIT: "12",
  });
  assert.deepEqual(config.oidcAlgorithms, ["RS256", "ES256"]);
  assert.equal(config.oidcTenantClaim, "org.id");
  assert.equal(config.taskRetentionSeconds, 7200);
  assert.equal(config.taskRateLimit, 12);

  assert.throws(
    () => loadConfig({ ...PRODUCTION_ENV, OIDC_ALGORITHMS: "HS256" }),
    /subset of RS256/,
  );
  assert.throws(
    () => loadConfig({ ...PRODUCTION_ENV, TASK_RETENTION_SECONDS: "299" }),
    /between 300/,
  );
});

test("Redis client certificates require a matching private key", () => {
  assert.throws(
    () =>
      loadConfig({
        ...VALID_ENV,
        REDIS_CERT_FILE: "/run/secrets/client.pem",
      }),
    /configured together/,
  );
});
