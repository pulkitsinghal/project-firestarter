import assert from "node:assert/strict";
import test from "node:test";

import { rateLimitKey } from "../../src/rate-limit.js";

test("rate-limit keys are scoped by namespace, owner, and fixed window", () => {
  assert.equal(
    rateLimitKey("notifier", "owner-a", 61_000, 60),
    "notifier:rate:owner-a:1",
  );
  assert.notEqual(
    rateLimitKey("notifier", "owner-a", 61_000, 60),
    rateLimitKey("notifier", "owner-b", 61_000, 60),
  );
  assert.notEqual(
    rateLimitKey("notifier", "owner-a", 61_000, 60),
    rateLimitKey("notifier", "owner-a", 121_000, 60),
  );
});
