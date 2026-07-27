const DEFAULTS = Object.freeze({
  port: 3000,
  redisUrl: "redis://localhost:6379",
  queueName: "{{ project_slug }}",
  eventChannel: "{{ project_slug }}:events",
  taskDelayMs: 1200,
  workerConcurrency: 4,
  taskRetentionSeconds: 24 * 60 * 60,
  taskRateLimit: 30,
  taskRateWindowSeconds: 60,
  replayLimit: 50,
  authMode: "anonymous",
  oidcAlgorithms: "RS256",
  oidcTenantClaim: "tenant_id",
});

const ALLOWED_OIDC_ALGORITHMS = new Set([
  "RS256",
  "PS256",
  "ES256",
  "EdDSA",
]);

function parseInteger(name, value, { min, max }) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new Error(`${name} must be an integer between ${min} and ${max}`);
  }
  return parsed;
}

function parseRedisUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("REDIS_URL must be a valid redis:// or rediss:// URL");
  }

  if (!["redis:", "rediss:"].includes(url.protocol)) {
    throw new Error("REDIS_URL must use redis:// or rediss://");
  }
  if (
    url.pathname &&
    url.pathname !== "/" &&
    !/^\/\d+$/.test(url.pathname)
  ) {
    throw new Error("REDIS_URL database path must be a non-negative integer");
  }

  return url;
}

function parsePublicOrigin(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("PUBLIC_ORIGIN must be a valid http:// or https:// origin");
  }

  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("PUBLIC_ORIGIN must contain only an http(s) scheme, host, and optional port");
  }

  return url.origin;
}

function parseHttpsUrl(name, value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} must be a valid https:// URL`);
  }

  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error(`${name} must use https:// without credentials, query, or fragment`);
  }
  return value;
}

function parseName(name, value, { allowColon = false } = {}) {
  const pattern = allowColon
    ? /^[A-Za-z0-9][A-Za-z0-9:_-]{0,79}$/
    : /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
  if (!pattern.test(value)) {
    throw new Error(`${name} contains unsupported characters`);
  }
  return value;
}

function parseRequiredText(name, value, { max = 256 } = {}) {
  if (typeof value !== "string" || !value.trim() || value.length > max) {
    throw new Error(`${name} must contain between 1 and ${max} characters`);
  }
  return value.trim();
}

function parseAuthMode(value) {
  if (!["anonymous", "oidc"].includes(value)) {
    throw new Error("AUTH_MODE must be anonymous or oidc");
  }
  return value;
}

function parseOidcAlgorithms(value) {
  const algorithms = value
    .split(",")
    .map((algorithm) => algorithm.trim())
    .filter(Boolean);
  if (
    algorithms.length === 0 ||
    new Set(algorithms).size !== algorithms.length ||
    algorithms.some((algorithm) => !ALLOWED_OIDC_ALGORITHMS.has(algorithm))
  ) {
    throw new Error(
      "OIDC_ALGORITHMS must be a unique comma-separated subset of RS256, PS256, ES256, or EdDSA",
    );
  }
  return Object.freeze(algorithms);
}

function parseOptionalPath(name, value) {
  if (value === undefined || value === "") {
    return null;
  }
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.includes("\0")
  ) {
    throw new Error(`${name} must be an absolute file path`);
  }
  return value;
}

export function loadConfig(env = process.env) {
  const nodeEnv = env.NODE_ENV ?? "development";
  const isProduction = nodeEnv === "production";
  const sessionSecret = env.SESSION_SECRET;
  const authMode = parseAuthMode(env.AUTH_MODE ?? DEFAULTS.authMode);
  const publicOrigin = parsePublicOrigin(
    env.PUBLIC_ORIGIN ?? `http://localhost:${env.PORT ?? DEFAULTS.port}`,
  );
  const redisUrl = parseRedisUrl(env.REDIS_URL ?? DEFAULTS.redisUrl);
  const redisTls = {
    caFile: parseOptionalPath("REDIS_CA_FILE", env.REDIS_CA_FILE),
    certFile: parseOptionalPath("REDIS_CERT_FILE", env.REDIS_CERT_FILE),
    keyFile: parseOptionalPath("REDIS_KEY_FILE", env.REDIS_KEY_FILE),
  };

  if (!sessionSecret || Buffer.byteLength(sessionSecret) < 32) {
    throw new Error("SESSION_SECRET must contain at least 32 bytes");
  }
  if (isProduction && !publicOrigin.startsWith("https://")) {
    throw new Error("PUBLIC_ORIGIN must use https:// in production");
  }
  if (isProduction && authMode !== "oidc") {
    throw new Error("AUTH_MODE must be oidc in production");
  }
  if (
    isProduction &&
    (
      redisUrl.protocol !== "rediss:" ||
      !redisUrl.username ||
      !redisUrl.password
    )
  ) {
    throw new Error(
      "production REDIS_URL must use rediss:// with an ACL username and password",
    );
  }
  if (Boolean(redisTls.certFile) !== Boolean(redisTls.keyFile)) {
    throw new Error("REDIS_CERT_FILE and REDIS_KEY_FILE must be configured together");
  }

  let oidcIssuer = null;
  let oidcAudience = null;
  let oidcJwksUrl = null;
  let oidcAlgorithms = Object.freeze([]);
  let oidcTenantClaim = null;
  if (authMode === "oidc") {
    oidcIssuer = parseHttpsUrl(
      "OIDC_ISSUER",
      parseRequiredText("OIDC_ISSUER", env.OIDC_ISSUER),
    );
    oidcAudience = parseRequiredText("OIDC_AUDIENCE", env.OIDC_AUDIENCE);
    oidcJwksUrl = parseHttpsUrl(
      "OIDC_JWKS_URL",
      parseRequiredText("OIDC_JWKS_URL", env.OIDC_JWKS_URL),
    );
    oidcAlgorithms = parseOidcAlgorithms(
      env.OIDC_ALGORITHMS ?? DEFAULTS.oidcAlgorithms,
    );
    oidcTenantClaim = parseRequiredText(
      "OIDC_TENANT_CLAIM",
      env.OIDC_TENANT_CLAIM ?? DEFAULTS.oidcTenantClaim,
      { max: 64 },
    );
    if (!/^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/.test(oidcTenantClaim)) {
      throw new Error("OIDC_TENANT_CLAIM must be a simple claim name");
    }
  }

  return Object.freeze({
    nodeEnv,
    isProduction,
    host: env.HOST ?? "127.0.0.1",
    port: parseInteger("PORT", env.PORT ?? DEFAULTS.port, {
      min: 1,
      max: 65535,
    }),
    redisUrl: redisUrl.toString(),
    redisTls: Object.freeze(redisTls),
    publicOrigin,
    queueName: parseName("QUEUE_NAME", env.QUEUE_NAME ?? DEFAULTS.queueName),
    eventChannel: parseName(
      "EVENT_CHANNEL",
      env.EVENT_CHANNEL ?? DEFAULTS.eventChannel,
      { allowColon: true },
    ),
    sessionSecret,
    taskDelayMs: parseInteger(
      "TASK_DELAY_MS",
      env.TASK_DELAY_MS ?? DEFAULTS.taskDelayMs,
      { min: 10, max: 30000 },
    ),
    workerConcurrency: parseInteger(
      "WORKER_CONCURRENCY",
      env.WORKER_CONCURRENCY ?? DEFAULTS.workerConcurrency,
      { min: 1, max: 64 },
    ),
    taskRetentionSeconds: parseInteger(
      "TASK_RETENTION_SECONDS",
      env.TASK_RETENTION_SECONDS ?? DEFAULTS.taskRetentionSeconds,
      { min: 300, max: 30 * 24 * 60 * 60 },
    ),
    taskRateLimit: parseInteger(
      "TASK_RATE_LIMIT",
      env.TASK_RATE_LIMIT ?? DEFAULTS.taskRateLimit,
      { min: 1, max: 1000 },
    ),
    taskRateWindowSeconds: parseInteger(
      "TASK_RATE_WINDOW_SECONDS",
      env.TASK_RATE_WINDOW_SECONDS ?? DEFAULTS.taskRateWindowSeconds,
      { min: 1, max: 60 * 60 },
    ),
    replayLimit: parseInteger(
      "REPLAY_LIMIT",
      env.REPLAY_LIMIT ?? DEFAULTS.replayLimit,
      { min: 1, max: 100 },
    ),
    authMode,
    oidcIssuer,
    oidcAudience,
    oidcJwksUrl,
    oidcAlgorithms,
    oidcTenantClaim,
  });
}
