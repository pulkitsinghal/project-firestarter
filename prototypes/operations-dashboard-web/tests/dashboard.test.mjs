import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { assertSanitizedSnapshot } from "../dashboard.js";

const fixtureURL = new URL("../fixtures/sanitized-remote.snapshot.json", import.meta.url);

async function fixture() {
  return JSON.parse(await readFile(fixtureURL, "utf8"));
}

test("the synthetic fixture has ten lanes across every lifecycle state", async () => {
  const snapshot = await fixture();
  assert.equal(assertSanitizedSnapshot(snapshot), snapshot);
  assert.equal(snapshot.queue.length, 10);
  assert.deepEqual(
    Object.fromEntries(
      ["running", "queued", "waiting", "ready"].map((state) => [
        state,
        snapshot.queue.filter((record) => record.state === state).length,
      ]),
    ),
    { running: 2, queued: 3, waiting: 2, ready: 3 },
  );
});

test("future additive queue metrics are accepted only within the coordinated bounds", async () => {
  const snapshot = await fixture();
  Object.assign(snapshot.queue[0], {
    completedSteps: 4,
    totalSteps: 10,
    currentStep: "Review synthetic layout",
    lastActiveSeconds: 0,
    memoryMB: 256,
    cpuPercent: 12.5,
  });
  assert.equal(assertSanitizedSnapshot(snapshot), snapshot);

  const partial = structuredClone(snapshot);
  delete partial.queue[0].totalSteps;
  assert.throws(() => assertSanitizedSnapshot(partial), /invalid step progress/);

  const invalidCPU = structuredClone(snapshot);
  invalidCPU.queue[0].cpuPercent = 100.1;
  assert.throws(() => assertSanitizedSnapshot(invalidCPU), /outside the supported range/);

  const invalidActivity = structuredClone(snapshot);
  invalidActivity.queue[0].lastActiveSeconds = 315360001;
  assert.throws(() => assertSanitizedSnapshot(invalidActivity), /outside the supported range/);
});

test("unknown fields, non-sanitized records, and private-looking values fail closed", async () => {
  const snapshot = await fixture();

  const unknown = structuredClone(snapshot);
  unknown.queue[0].extra = "unsupported";
  assert.throws(() => assertSanitizedSnapshot(unknown), /unsupported fields/);

  const localOnly = structuredClone(snapshot);
  localOnly.queue[0].exposure = "local-only";
  assert.throws(() => assertSanitizedSnapshot(localOnly), /Non-sanitized record rejected/);

  const privateValue = structuredClone(snapshot);
  privateValue.queue[0].detail = ["https", "://", "example.invalid"].join("");
  assert.throws(() => assertSanitizedSnapshot(privateValue), /private-looking content/);
});

test("missing evidence remains explicit instead of being converted to passing", async () => {
  const snapshot = await fixture();
  assert.equal(snapshot.tests.some((record) => record.result === "passed"), false);
  assert.equal(snapshot.tests.some((record) => record.result === "not-run"), true);
  assert.equal(snapshot.tests.some((record) => record.result === "not-implemented"), true);
  assert.equal(snapshot.signals.some((record) => record.state === "unavailable"), true);
  assert.equal(snapshot.resourceBudget.some((record) => record.displayValue === "Not supplied"), true);
});
