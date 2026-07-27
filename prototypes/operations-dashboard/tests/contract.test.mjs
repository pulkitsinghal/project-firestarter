import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  assertDashboardSnapshot,
  assertPrivacyNeutralSnapshot,
} from "../contract/validate-dashboard.mjs";
import {
  assertSanitizedSnapshot as assertWebSnapshot,
} from "../../operations-dashboard-web/dashboard.js";

const fixtureURL = new URL("../contract/dashboard-state.sample.json", import.meta.url);
const schemaURL = new URL("../contract/dashboard-state.schema.json", import.meta.url);
const webFixtureURL = new URL(
  "../../operations-dashboard-web/fixtures/sanitized-remote.snapshot.json",
  import.meta.url,
);

async function readJSON(url) {
  return JSON.parse(await readFile(url, "utf8"));
}

test("the committed fixture satisfies the native contract and privacy boundary", async () => {
  const fixture = await readJSON(fixtureURL);
  assert.equal(assertDashboardSnapshot(fixture, { surface: "native" }), fixture);
  assert.equal(assertPrivacyNeutralSnapshot(fixture), fixture);
});

test("the web fixture satisfies the shared sanitized-remote contract", async () => {
  const fixture = await readJSON(webFixtureURL);
  assert.equal(assertDashboardSnapshot(fixture, { surface: "web" }), fixture);
  assert.equal(assertPrivacyNeutralSnapshot(fixture), fixture);
});

test("the schema exposes the canonical consumer sections and no transport fields", async () => {
  const schema = await readJSON(schemaURL);
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(
    Object.keys(schema.properties).sort(),
    ["mode", "queue", "resourceBudget", "schemaVersion", "signals", "tests"],
  );

  for (const definition of [
    schema.$defs.queueRecord,
    schema.$defs.testRecord,
    schema.$defs.resourceBudgetRecord,
    schema.$defs.signalRecord,
  ]) {
    assert.ok(definition.required.includes("exposure"));
    assert.ok(definition.required.includes("verification"));
  }

  assert.deepEqual(
    Object.keys(schema.$defs.queueRecord.properties).sort(),
    [
      "completedSteps",
      "cpuPercent",
      "currentStep",
      "detail",
      "exposure",
      "id",
      "lastActiveSeconds",
      "memoryMB",
      "state",
      "title",
      "totalSteps",
      "verification",
    ],
  );

  const serialized = JSON.stringify(schema);
  assert.doesNotMatch(
    serialized,
    /endpoint|hostname|localUrl|tailnetUrl|ipAddress|filePath|snapshotKind|qualityChecks/i,
  );
});

test("queue progress and resource evidence is optional, bounded, and internally consistent", async () => {
  const fixture = await readJSON(fixtureURL);
  const legacyCompatible = structuredClone(fixture);
  for (const record of legacyCompatible.queue) {
    delete record.completedSteps;
    delete record.totalSteps;
    delete record.currentStep;
    delete record.lastActiveSeconds;
    delete record.memoryMB;
    delete record.cpuPercent;
  }
  assert.doesNotThrow(() => assertDashboardSnapshot(legacyCompatible));

  const unpaired = structuredClone(fixture);
  delete unpaired.queue[0].totalSteps;
  assert.throws(() => assertDashboardSnapshot(unpaired), /supplied together/);

  const regressed = structuredClone(fixture);
  regressed.queue[0].completedSteps = 6;
  regressed.queue[0].totalSteps = 5;
  assert.throws(() => assertDashboardSnapshot(regressed), /cannot exceed/);

  const excessiveCPU = structuredClone(fixture);
  excessiveCPU.queue[0].cpuPercent = 100.1;
  assert.throws(() => assertDashboardSnapshot(excessiveCPU), /no greater than 100/);
});

test("web snapshots require sanitized-remote mode and sanitized records", async () => {
  const fixture = await readJSON(fixtureURL);
  assert.throws(
    () => assertDashboardSnapshot(fixture, { surface: "web" }),
    /requires sanitized-remote/,
  );

  const web = structuredClone(fixture);
  web.mode = "sanitized-remote";
  assert.doesNotThrow(() => assertDashboardSnapshot(web, { surface: "web" }));

  const local = structuredClone(fixture);
  local.mode = "local";
  local.queue[0].exposure = "local-only";
  local.queue[0].verification = "verified";
  assert.doesNotThrow(() => assertDashboardSnapshot(local, { surface: "native" }));
  assert.throws(() => assertDashboardSnapshot(local, { surface: "web" }), /sanitized-remote/);

  local.queue[0].verification = "estimated";
  assert.throws(
    () => assertDashboardSnapshot(local, { surface: "native" }),
    /require verified/,
  );
});

test("all record types enforce verification and exposure", async () => {
  const fixture = await readJSON(fixtureURL);
  for (const section of ["queue", "tests", "resourceBudget", "signals"]) {
    const missingVerification = structuredClone(fixture);
    delete missingVerification[section][0].verification;
    assert.throws(
      () => assertDashboardSnapshot(missingVerification),
      /missing required keys/,
    );

    const missingExposure = structuredClone(fixture);
    delete missingExposure[section][0].exposure;
    assert.throws(() => assertDashboardSnapshot(missingExposure), /missing required keys/);
  }
});

test("unknown fields and private-looking strings fail closed", async () => {
  const fixture = await readJSON(fixtureURL);
  const unknownField = { ...fixture, endpoint: "not allowed" };
  assert.throws(() => assertDashboardSnapshot(unknownField), /unsupported keys/);

  const privateExamples = [
    ["http:", "/", "/", "local", "host"].join(""),
    ["device", "example", "invalid"].join("."),
    ["100", "64", "0", "1"].join("."),
    ["", "Users", "example", "private"].join("/"),
    ["operator", "example.invalid"].join("@"),
    ["secret", "token"].join(" "),
  ];
  for (const example of privateExamples) {
    const unsafe = structuredClone(fixture);
    unsafe.queue[0].detail = example;
    assert.throws(() => assertPrivacyNeutralSnapshot(unsafe));
  }
});

test("the browser renderer independently rejects contract drift and private values", async () => {
  const fixture = await readJSON(webFixtureURL);
  assert.equal(assertWebSnapshot(fixture), fixture);

  const legacy = structuredClone(fixture);
  legacy.snapshotKind = legacy.mode;
  delete legacy.mode;
  assert.throws(() => assertWebSnapshot(legacy), /unsupported fields/);

  const invalidState = structuredClone(fixture);
  invalidState.queue[0].state = "next";
  assert.throws(() => assertWebSnapshot(invalidState), /unsupported value/);

  const privateValue = structuredClone(fixture);
  privateValue.signals[0].detail = ["", "Users", "example", "private"].join("/");
  assert.throws(() => assertWebSnapshot(privateValue), /private-looking content/);

  const privateValues = [
    ["file:", "/", "/", "private", ".json"].join(""),
    ["service", ".", "example", ".", "internal"].join(""),
    ["device", ".", "ts", ".", "net"].join(""),
    "1f70c8b2-9ad6-4a61-9b89-f2a84e08cb53",
    ["C:", "\\", "Users", "\\", "example"].join(""),
  ];
  for (const detail of privateValues) {
    const candidate = structuredClone(fixture);
    candidate.signals[0].detail = detail;
    assert.throws(
      () => assertWebSnapshot(candidate),
      /private-looking content/,
      detail,
    );
  }
});
