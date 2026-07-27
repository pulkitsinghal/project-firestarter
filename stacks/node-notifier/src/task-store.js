export class TaskStore {
  constructor(
    redis,
    {
      namespace,
      retentionSeconds,
    },
  ) {
    this.redis = redis;
    this.namespace = namespace;
    this.retentionSeconds = retentionSeconds;
  }

  indexKey(ownerKey) {
    return `${this.namespace}:owner:${ownerKey}:tasks`;
  }

  acknowledgementKey(taskId) {
    return `${this.namespace}:ack:${taskId}`;
  }

  async remember(ownerKey, taskId, now = Date.now()) {
    const key = this.indexKey(ownerKey);
    await this.redis
      .multi()
      .zadd(key, now, taskId)
      .expire(key, this.retentionSeconds)
      .exec();
  }

  async forget(ownerKey, taskId) {
    await this.redis.zrem(this.indexKey(ownerKey), taskId);
  }

  async listTaskIds(ownerKey, limit, now = Date.now()) {
    const key = this.indexKey(ownerKey);
    const cutoff = now - this.retentionSeconds * 1000;
    const transaction = await this.redis
      .multi()
      .zremrangebyscore(key, "-inf", cutoff)
      .zrevrange(key, 0, limit - 1)
      .expire(key, this.retentionSeconds)
      .exec();
    return transaction?.[1]?.[1] ?? [];
  }

  async acknowledgement(taskId) {
    const value = await this.redis.get(this.acknowledgementKey(taskId));
    return value ? JSON.parse(value) : null;
  }

  async acknowledge(taskId, now = Date.now()) {
    const key = this.acknowledgementKey(taskId);
    const acknowledgement = {
      acknowledgedAt: new Date(now).toISOString(),
    };
    const stored = await this.redis.set(
      key,
      JSON.stringify(acknowledgement),
      "EX",
      this.retentionSeconds,
      "NX",
    );
    if (stored) {
      return acknowledgement;
    }
    return this.acknowledgement(taskId);
  }
}
