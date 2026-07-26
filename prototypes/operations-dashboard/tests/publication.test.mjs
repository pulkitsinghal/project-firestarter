import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  buildRelease,
  commitReleaseTransition,
  sanitizeSnapshot,
  verifyRelease,
} from "../bin/publish-sanitized.mjs";

function recordMetadata(exposure = "sanitized", verification = "verified") {
  return { exposure, verification };
}

function localSnapshot(label = "First") {
  return {
    schemaVersion: "1.0",
    mode: "local",
    queue: [
      {
        id: "SAFE-Q1",
        title: `${label} sanitized queue record`,
        detail: "Approved for the remote snapshot.",
        state: "running",
        ...recordMetadata(),
      },
      {
        id: "LOCAL-Q1",
        title: "Private local queue record",
        detail: "Visible to the native surface only.",
        state: "waiting",
        ...recordMetadata("local-only"),
      },
    ],
    tests: [
      {
        id: "SAFE-T1",
        title: "Sanitized test result",
        detail: "A generic local validation passed.",
        result: "passed",
        ...recordMetadata(),
      },
      {
        id: "LOCAL-T1",
        title: "Private local test",
        detail: "Visible to the native surface only.",
        result: "passed",
        ...recordMetadata("local-only"),
      },
    ],
    resourceBudget: [
      {
        id: "SAFE-R1",
        title: "Publication lane",
        detail: "A generic bounded-work indicator.",
        displayValue: "Available",
        ...recordMetadata(),
      },
      {
        id: "LOCAL-R1",
        title: "Private local budget",
        detail: "Visible to the native surface only.",
        displayValue: "Local only",
        ...recordMetadata("local-only"),
      },
    ],
    signals: [
      {
        id: "SAFE-S1",
        title: "Sanitized availability",
        detail: "No device value is included.",
        state: "available",
        ...recordMetadata(),
      },
      {
        id: "LOCAL-S1",
        title: "Private local signal",
        detail: "Visible to the native surface only.",
        state: "available",
        ...recordMetadata("local-only"),
      },
    ],
  };
}

test("sanitization keeps allowlisted records and drops every local-only record", () => {
  const sanitized = sanitizeSnapshot(localSnapshot());

  assert.equal(sanitized.mode, "sanitized-remote");
  for (const section of ["queue", "tests", "resourceBudget", "signals"]) {
    assert.equal(sanitized[section].length, 1);
    assert.equal(sanitized[section][0].exposure, "sanitized");
    assert.equal(sanitized[section][0].verification, "verified");
  }
  assert.deepEqual(Object.keys(sanitized).sort(), [
    "mode",
    "queue",
    "resourceBudget",
    "schemaVersion",
    "signals",
    "tests",
  ]);
});

test("an unverified local-only record fails before it can be filtered", () => {
  const source = localSnapshot();
  source.queue[1].verification = "estimated";

  assert.throws(() => sanitizeSnapshot(source), /local-only records require verified/);
});

test("private-looking content marked sanitized fails closed", () => {
  const source = localSnapshot();
  source.queue[0].detail = ["http:", "/", "/", "local", "host"].join("");

  assert.throws(() => sanitizeSnapshot(source), /forbidden URL/);
});

test("release builds are deterministic, idempotent, and tamper evident", async () => {
  const directory = await mkdtemp(join(tmpdir(), "operations-publication-unit-"));
  const inputPath = join(directory, "input.json");
  const outputRoot = join(directory, "output");
  try {
    await writeFile(inputPath, JSON.stringify(localSnapshot()), "utf8");
    const first = await buildRelease({ inputPath, outputRoot });
    const second = await buildRelease({ inputPath, outputRoot });

    assert.equal(first.releaseId, second.releaseId);
    assert.equal(first.reused, false);
    assert.equal(second.reused, true);
    await assert.doesNotReject(
      verifyRelease({ outputRoot, releaseId: first.releaseId }),
    );

    const dashboardPath = join(
      outputRoot,
      "releases",
      first.releaseId,
      "dashboard.js",
    );
    const dashboard = await readFile(dashboardPath, "utf8");
    await writeFile(dashboardPath, `${dashboard}\n`, "utf8");
    await assert.rejects(
      verifyRelease({ outputRoot, releaseId: first.releaseId }),
      /hash mismatch/,
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("the publisher rejects an oversized source before parsing it", async () => {
  const directory = await mkdtemp(join(tmpdir(), "operations-publication-size-"));
  const inputPath = join(directory, "oversized.json");
  try {
    await writeFile(inputPath, Buffer.alloc(1_048_577, 0x20));
    await assert.rejects(
      buildRelease({ inputPath, outputRoot: join(directory, "output") }),
      /one-megabyte safety limit/,
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("a history commit failure restores the previously active release", async () => {
  const events = [];
  const historyError = new Error("simulated history commit failure");

  await assert.rejects(
    commitReleaseTransition({
      outputRoot: "/unused",
      releaseId: "new-release",
      previousReleaseId: "previous-release",
      history: { formatVersion: "1", releaseIds: ["previous-release"] },
      operation: "test transition",
      prepareHistory: async () => {
        events.push("history prepared");
        return {
          commit: async () => {
            events.push("history commit attempted");
            throw historyError;
          },
          cleanup: async () => {
            events.push("history staging cleaned");
          },
        };
      },
      switchRelease: async (_outputRoot, releaseId) => {
        events.push(`switched to ${releaseId}`);
      },
      restoreRelease: async (_outputRoot, releaseId) => {
        events.push(`restored ${releaseId}`);
      },
    }),
    historyError,
  );

  assert.deepEqual(events, [
    "history prepared",
    "switched to new-release",
    "history commit attempted",
    "restored previous-release",
    "history staging cleaned",
  ]);
});
