#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  readFile,
  readlink,
  readdir,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertDashboardSnapshot,
  assertPrivacyNeutralSnapshot,
} from "../contract/validate-dashboard.mjs";

const FORMAT_VERSION = "1";
const RELEASE_ID_PATTERN = /^[a-f0-9]{64}$/;
const WEB_SOURCE = fileURLToPath(
  new URL("../../operations-dashboard-web/", import.meta.url),
);
const STATIC_ASSETS = ["dashboard.js", "index.html", "styles.css"];
const SNAPSHOT_FILE = "fixtures/sanitized-remote.snapshot.json";
const MANIFEST_FILE = "release-manifest.json";
const HISTORY_FILE = "history.json";
const CURRENT_LINK = "current";
const MAXIMUM_SOURCE_BYTES = 1_048_576;

function fail(message) {
  throw new TypeError(message);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalJSON(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function assertReleaseId(releaseId) {
  if (!RELEASE_ID_PATTERN.test(releaseId)) {
    fail("release id must be a full lowercase SHA-256 digest");
  }
}

function pathsFor(outputRoot) {
  const root = resolve(outputRoot);
  return {
    root,
    releases: join(root, "releases"),
    current: join(root, CURRENT_LINK),
    history: join(root, HISTORY_FILE),
  };
}

function releasePath(outputRoot, releaseId) {
  assertReleaseId(releaseId);
  const paths = pathsFor(outputRoot);
  const candidate = resolve(paths.releases, releaseId);
  if (
    !candidate.startsWith(`${paths.releases}${sep}`)
    || dirname(candidate) !== paths.releases
  ) {
    fail("release path escaped the configured publication root");
  }
  return candidate;
}

function queueRecord(record) {
  const sanitized = {
    id: record.id,
    title: record.title,
    detail: record.detail,
    state: record.state,
    exposure: record.exposure,
    verification: record.verification,
  };
  for (const key of [
    "completedSteps",
    "totalSteps",
    "currentStep",
    "lastActiveSeconds",
    "memoryMB",
    "cpuPercent",
  ]) {
    if (record[key] !== undefined) sanitized[key] = record[key];
  }
  return sanitized;
}

function testRecord(record) {
  return {
    id: record.id,
    title: record.title,
    detail: record.detail,
    result: record.result,
    exposure: record.exposure,
    verification: record.verification,
  };
}

function resourceBudgetRecord(record) {
  const sanitized = {
    id: record.id,
    title: record.title,
    detail: record.detail,
    displayValue: record.displayValue,
    exposure: record.exposure,
    verification: record.verification,
  };
  if (record.value !== undefined) sanitized.value = record.value;
  if (record.capacity !== undefined) sanitized.capacity = record.capacity;
  return sanitized;
}

function signalRecord(record) {
  return {
    id: record.id,
    title: record.title,
    detail: record.detail,
    state: record.state,
    exposure: record.exposure,
    verification: record.verification,
  };
}

export function sanitizeSnapshot(snapshot) {
  assertDashboardSnapshot(snapshot, { surface: "native" });
  if (snapshot.mode !== "local") {
    fail("publication input must use local mode");
  }

  const sanitized = {
    schemaVersion: snapshot.schemaVersion,
    mode: "sanitized-remote",
    queue: snapshot.queue.filter(isSanitized).map(queueRecord),
    tests: snapshot.tests.filter(isSanitized).map(testRecord),
    resourceBudget: snapshot.resourceBudget
      .filter(isSanitized)
      .map(resourceBudgetRecord),
    signals: snapshot.signals.filter(isSanitized).map(signalRecord),
  };

  assertDashboardSnapshot(sanitized, { surface: "web" });
  assertPrivacyNeutralSnapshot(sanitized);
  return sanitized;
}

function isSanitized(record) {
  return record.exposure === "sanitized";
}

async function readSourceSnapshot(inputPath) {
  const path = resolve(inputPath);
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink()) {
    fail("publication input must be a regular file");
  }
  if (info.size > MAXIMUM_SOURCE_BYTES) {
    fail("publication input exceeds the one-megabyte safety limit");
  }
  const serialized = await readFile(path, "utf8");
  return JSON.parse(serialized);
}

async function buildFilePayloads(snapshot) {
  const payloads = new Map();
  for (const asset of STATIC_ASSETS) {
    payloads.set(asset, await readFile(join(WEB_SOURCE, asset)));
  }
  payloads.set(SNAPSHOT_FILE, Buffer.from(canonicalJSON(snapshot), "utf8"));
  return payloads;
}

function manifestFor(payloads) {
  const files = Object.fromEntries(
    [...payloads.entries()]
      .map(([name, value]) => [name, sha256(value)])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
  const releaseId = sha256(canonicalJSON(files));
  return {
    formatVersion: FORMAT_VERSION,
    releaseId,
    snapshotSha256: files[SNAPSHOT_FILE],
    files,
  };
}

async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

async function writePayloads(directory, payloads, manifest) {
  await mkdir(join(directory, "fixtures"), { recursive: true, mode: 0o755 });
  for (const [name, value] of payloads) {
    await writeFile(join(directory, name), value, { flag: "wx", mode: 0o644 });
  }
  await writeFile(
    join(directory, MANIFEST_FILE),
    canonicalJSON(manifest),
    { flag: "wx", mode: 0o644 },
  );
}

export async function buildRelease({ inputPath, outputRoot }) {
  const source = await readSourceSnapshot(inputPath);
  const snapshot = sanitizeSnapshot(source);
  const payloads = await buildFilePayloads(snapshot);
  const manifest = manifestFor(payloads);
  const paths = pathsFor(outputRoot);
  const destination = releasePath(outputRoot, manifest.releaseId);

  await mkdir(paths.releases, { recursive: true, mode: 0o755 });
  if (await pathExists(destination)) {
    await verifyRelease({ outputRoot, releaseId: manifest.releaseId });
    return { releaseId: manifest.releaseId, reused: true };
  }

  const staging = join(paths.root, `.staging-${randomUUID()}`);
  await mkdir(staging, { mode: 0o700 });
  try {
    await writePayloads(staging, payloads, manifest);
    try {
      await rename(staging, destination);
    } catch (error) {
      if (error?.code !== "EEXIST" && error?.code !== "ENOTEMPTY") throw error;
      await verifyRelease({ outputRoot, releaseId: manifest.releaseId });
    }
  } finally {
    await rm(staging, { recursive: true, force: true });
  }

  await verifyRelease({ outputRoot, releaseId: manifest.releaseId });
  return { releaseId: manifest.releaseId, reused: false };
}

async function listReleaseFiles(directory, prefix = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  const names = [];
  for (const entry of entries) {
    const name = prefix ? `${prefix}/${entry.name}` : entry.name;
    const path = join(directory, entry.name);
    if (entry.isSymbolicLink()) fail(`release contains a symbolic link: ${name}`);
    if (entry.isDirectory()) {
      names.push(...await listReleaseFiles(path, name));
    } else if (entry.isFile()) {
      names.push(name);
    } else {
      fail(`release contains an unsupported filesystem entry: ${name}`);
    }
  }
  return names.sort();
}

function assertManifest(manifest, expectedReleaseId) {
  const keys = Object.keys(manifest).sort();
  if (
    JSON.stringify(keys)
    !== JSON.stringify(["files", "formatVersion", "releaseId", "snapshotSha256"])
  ) {
    fail("release manifest has unsupported fields");
  }
  if (manifest.formatVersion !== FORMAT_VERSION) {
    fail("unsupported release manifest version");
  }
  if (manifest.releaseId !== expectedReleaseId) {
    fail("release manifest id does not match its directory");
  }
  assertReleaseId(manifest.releaseId);
  if (
    manifest.files === null
    || typeof manifest.files !== "object"
    || Array.isArray(manifest.files)
  ) {
    fail("release manifest files must be an object");
  }
}

export async function verifyRelease({ outputRoot, releaseId }) {
  const directory = releasePath(outputRoot, releaseId);
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    fail("release must be a real directory");
  }

  const manifest = JSON.parse(await readFile(join(directory, MANIFEST_FILE), "utf8"));
  assertManifest(manifest, releaseId);

  const expectedFiles = [...STATIC_ASSETS, SNAPSHOT_FILE, MANIFEST_FILE].sort();
  const actualFiles = await listReleaseFiles(directory);
  if (JSON.stringify(actualFiles) !== JSON.stringify(expectedFiles)) {
    fail("release contains missing or unexpected files");
  }

  const payloads = new Map();
  for (const name of [...STATIC_ASSETS, SNAPSHOT_FILE]) {
    const value = await readFile(join(directory, name));
    payloads.set(name, value);
    if (manifest.files[name] !== sha256(value)) {
      fail(`release hash mismatch: ${name}`);
    }
  }

  const expectedManifest = manifestFor(payloads);
  if (
    manifest.snapshotSha256 !== expectedManifest.snapshotSha256
    || manifest.releaseId !== expectedManifest.releaseId
    || JSON.stringify(manifest.files) !== JSON.stringify(expectedManifest.files)
  ) {
    fail("release manifest does not match its content");
  }

  const snapshot = JSON.parse(payloads.get(SNAPSHOT_FILE).toString("utf8"));
  assertDashboardSnapshot(snapshot, { surface: "web" });
  assertPrivacyNeutralSnapshot(snapshot);
  return { releaseId, verified: true };
}

async function readHistory(outputRoot) {
  const { history } = pathsFor(outputRoot);
  if (!(await pathExists(history))) {
    return { formatVersion: FORMAT_VERSION, releaseIds: [] };
  }
  const value = JSON.parse(await readFile(history, "utf8"));
  if (
    value?.formatVersion !== FORMAT_VERSION
    || !Array.isArray(value.releaseIds)
    || value.releaseIds.some((releaseId) => !RELEASE_ID_PATTERN.test(releaseId))
    || Object.keys(value).sort().join(",") !== "formatVersion,releaseIds"
  ) {
    fail("publication history is invalid");
  }
  return value;
}

async function prepareAtomicWrite(path, contents) {
  const staging = `${path}.next-${randomUUID()}`;
  try {
    await writeFile(staging, contents, { flag: "wx", mode: 0o644 });
  } catch (error) {
    await rm(staging, { force: true });
    throw error;
  }
  return {
    commit: () => rename(staging, path),
    cleanup: () => rm(staging, { force: true }),
  };
}

export async function readActiveReleaseId(outputRoot) {
  const paths = pathsFor(outputRoot);
  if (!(await pathExists(paths.current))) return null;
  const info = await lstat(paths.current);
  if (!info.isSymbolicLink()) fail("current publication entry must be a symbolic link");
  const target = await readlink(paths.current);
  const resolvedTarget = resolve(paths.root, target);
  const expectedParent = paths.releases;
  if (
    !resolvedTarget.startsWith(`${expectedParent}${sep}`)
    || dirname(resolvedTarget) !== expectedParent
  ) {
    fail("current publication link escaped the release directory");
  }
  const releaseId = relative(expectedParent, resolvedTarget);
  assertReleaseId(releaseId);
  await verifyRelease({ outputRoot, releaseId });
  return releaseId;
}

async function switchCurrent(outputRoot, releaseId) {
  const paths = pathsFor(outputRoot);
  await mkdir(paths.root, { recursive: true, mode: 0o755 });
  await verifyRelease({ outputRoot, releaseId });

  const staging = join(paths.root, `.current-${randomUUID()}`);
  const target = join("releases", releaseId);
  try {
    await symlink(target, staging);
    await rename(staging, paths.current);
  } finally {
    await rm(staging, { force: true });
  }
}

async function restoreCurrent(outputRoot, releaseId) {
  if (releaseId === null) {
    await rm(pathsFor(outputRoot).current, { force: true });
    return;
  }
  await switchCurrent(outputRoot, releaseId);
}

export async function commitReleaseTransition({
  outputRoot,
  releaseId,
  previousReleaseId,
  history,
  operation,
  prepareHistory = prepareAtomicWrite,
  switchRelease = switchCurrent,
  restoreRelease = restoreCurrent,
}) {
  const preparedHistory = await prepareHistory(
    pathsFor(outputRoot).history,
    canonicalJSON(history),
  );
  try {
    await switchRelease(outputRoot, releaseId);
    try {
      await preparedHistory.commit();
    } catch (historyError) {
      try {
        await restoreRelease(outputRoot, previousReleaseId);
      } catch (recoveryError) {
        throw new AggregateError(
          [historyError, recoveryError],
          `${operation} failed and the active release could not be restored`,
        );
      }
      throw historyError;
    }
  } finally {
    await preparedHistory.cleanup();
  }
}

export async function activateRelease({ outputRoot, releaseId }) {
  const currentReleaseId = await readActiveReleaseId(outputRoot);
  if (currentReleaseId === releaseId) {
    return { releaseId, previousReleaseId: null, changed: false };
  }

  const history = await readHistory(outputRoot);
  if (currentReleaseId !== null) history.releaseIds.push(currentReleaseId);
  await commitReleaseTransition({
    outputRoot,
    releaseId,
    previousReleaseId: currentReleaseId,
    history,
    operation: "activation",
  });
  return { releaseId, previousReleaseId: currentReleaseId, changed: true };
}

export async function rollbackRelease({ outputRoot }) {
  const currentReleaseId = await readActiveReleaseId(outputRoot);
  if (currentReleaseId === null) fail("there is no active release to roll back");

  const history = await readHistory(outputRoot);
  const releaseId = history.releaseIds.pop();
  if (releaseId === undefined) fail("there is no previous release to restore");

  history.releaseIds.push(currentReleaseId);
  await commitReleaseTransition({
    outputRoot,
    releaseId,
    previousReleaseId: currentReleaseId,
    history,
    operation: "rollback",
  });
  return { releaseId, replacedReleaseId: currentReleaseId, changed: true };
}

export async function publicationStatus({ outputRoot }) {
  const releaseId = await readActiveReleaseId(outputRoot);
  const history = await readHistory(outputRoot);
  return {
    releaseId,
    rollbackAvailable: history.releaseIds.length > 0,
  };
}

function parseOptions(argumentsToParse) {
  const options = {};
  for (let index = 0; index < argumentsToParse.length; index += 2) {
    const key = argumentsToParse[index];
    const value = argumentsToParse[index + 1];
    if (!key?.startsWith("--") || value === undefined || value.startsWith("--")) {
      fail("options must be provided as --name value pairs");
    }
    const name = key.slice(2);
    if (name in options) fail(`duplicate option: ${key}`);
    options[name] = value;
  }
  return options;
}

function requireOptions(options, required, allowed = required) {
  const unknown = Object.keys(options).filter((name) => !allowed.includes(name));
  const missing = required.filter((name) => !(name in options));
  if (unknown.length > 0) fail(`unsupported options: ${unknown.join(", ")}`);
  if (missing.length > 0) fail(`missing options: ${missing.join(", ")}`);
}

async function runCLI(argumentsToParse) {
  const [command, ...optionArguments] = argumentsToParse;
  const options = parseOptions(optionArguments);
  switch (command) {
    case "build":
      requireOptions(options, ["input", "output-root"]);
      return buildRelease({
        inputPath: options.input,
        outputRoot: options["output-root"],
      });
    case "verify":
      requireOptions(options, ["output-root", "release-id"]);
      return verifyRelease({
        outputRoot: options["output-root"],
        releaseId: options["release-id"],
      });
    case "activate":
      requireOptions(options, ["output-root", "release-id"]);
      return activateRelease({
        outputRoot: options["output-root"],
        releaseId: options["release-id"],
      });
    case "rollback":
      requireOptions(options, ["output-root"]);
      return rollbackRelease({ outputRoot: options["output-root"] });
    case "status":
      requireOptions(options, ["output-root"]);
      return publicationStatus({ outputRoot: options["output-root"] });
    default:
      fail("command must be build, verify, activate, rollback, or status");
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  runCLI(process.argv.slice(2))
    .then((result) => {
      process.stdout.write(canonicalJSON(result));
    })
    .catch((error) => {
      process.stderr.write(`publication failed: ${error.message}\n`);
      process.exitCode = 1;
    });
}
