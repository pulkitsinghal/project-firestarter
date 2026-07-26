import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  assertDashboardSnapshot,
  assertPrivacyNeutralSnapshot,
} from "../contract/validate-dashboard.mjs";

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

  const serialized = JSON.stringify(schema);
  assert.doesNotMatch(
    serialized,
    /endpoint|hostname|localUrl|tailnetUrl|ipAddress|filePath|snapshotKind|qualityChecks/i,
  );
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
