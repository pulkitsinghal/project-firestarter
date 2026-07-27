import assert from "node:assert/strict";
import test from "node:test";

import {
  jobOptions,
  redisConnectionOptions,
} from "../../src/queue.js";

test("jobs use bounded retries and retention", () => {
  const options = jobOptions(7200);
  assert.deepEqual(options.backoff, {
    type: "exponential",
    delay: 500,
  });
  assert.equal(options.attempts, 3);
  assert.equal(options.removeOnComplete.age, 7200);
  assert.equal(options.removeOnFail.age, 7200);
});

test("Redis URL parsing preserves credentials and loads TLS files", () => {
  const options = redisConnectionOptions(
    "rediss://queue-user:p%40ss@example.test:6380/2",
    {
      caFile: "/secrets/ca.pem",
      certFile: "/secrets/client.pem",
      keyFile: "/secrets/client-key.pem",
    },
    (file) => Buffer.from(file),
  );

  assert.equal(options.host, "example.test");
  assert.equal(options.port, 6380);
  assert.equal(options.username, "queue-user");
  assert.equal(options.password, "p@ss");
  assert.equal(options.db, 2);
  assert.equal(options.tls.servername, "example.test");
  assert.equal(options.tls.ca.toString(), "/secrets/ca.pem");
  assert.equal(options.tls.cert.toString(), "/secrets/client.pem");
  assert.equal(options.tls.key.toString(), "/secrets/client-key.pem");
  assert.equal(options.maxRetriesPerRequest, null);
});
