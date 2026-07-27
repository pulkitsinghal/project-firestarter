export function rateLimitKey(namespace, ownerKey, now, windowSeconds) {
  const bucket = Math.floor(now / 1000 / windowSeconds);
  return `${namespace}:rate:${ownerKey}:${bucket}`;
}

export async function consumeRateLimit(
  redis,
  {
    namespace,
    ownerKey,
    limit,
    windowSeconds,
    now = Date.now(),
  },
) {
  const resetAt = (Math.floor(now / 1000 / windowSeconds) + 1) * windowSeconds;
  const key = rateLimitKey(namespace, ownerKey, now, windowSeconds);
  const results = await redis
    .multi()
    .incr(key)
    .expireat(key, resetAt + 1)
    .exec();
  const count = Number(results?.[0]?.[1]);
  if (!Number.isInteger(count)) {
    throw new Error("Rate limiter did not receive a valid Redis response");
  }
  return Object.freeze({
    allowed: count <= limit,
    limit,
    remaining: Math.max(0, limit - count),
    resetAt,
  });
}
