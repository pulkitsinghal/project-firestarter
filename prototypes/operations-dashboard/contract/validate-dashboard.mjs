const rootKeys = ["schemaVersion", "mode", "queue", "tests", "resourceBudget", "signals"];
const queueRequiredKeys = ["id", "title", "detail", "state", "exposure", "verification"];
const queueOptionalKeys = [
  "completedSteps",
  "totalSteps",
  "currentStep",
  "lastActiveSeconds",
  "memoryMB",
  "cpuPercent",
];
const queueKeys = [...queueRequiredKeys, ...queueOptionalKeys];
const testKeys = ["id", "title", "detail", "result", "exposure", "verification"];
const budgetRequiredKeys = [
  "id",
  "title",
  "detail",
  "displayValue",
  "exposure",
  "verification",
];
const budgetKeys = [...budgetRequiredKeys, "value", "capacity"];
const signalKeys = ["id", "title", "detail", "state", "exposure", "verification"];

const modes = new Set(["sample", "local", "sanitized-remote"]);
const queueStates = new Set(["running", "queued", "waiting", "ready"]);
const testResults = new Set([
  "passed",
  "failed",
  "queued",
  "not-run",
  "not-implemented",
  "unknown",
]);
const signalStates = new Set(["available", "attention", "unavailable", "unknown"]);
const verifications = new Set(["verified", "estimated", "unavailable", "not-implemented"]);
const exposures = new Set(["sanitized", "local-only"]);

const privatePatterns = [
  { label: "URL", pattern: /\b(?:https?|file|ssh):\/\//i },
  {
    label: "loopback or private network name",
    pattern: /\b(?:localhost|tailnet|tailscale)\b|\.local\b|\.ts\.net\b/i,
  },
  { label: "IP address", pattern: /\b(?:\d{1,3}\.){3}\d{1,3}\b/ },
  {
    label: "hostname",
    pattern:
      /\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\b/i,
  },
  { label: "home-directory path", pattern: /(?:\/Users\/|\/home\/|[A-Za-z]:\\)/ },
  { label: "email address", pattern: /\b[^@\s]+@[^@\s]+\.[^@\s]+\b/ },
  {
    label: "credential term",
    pattern: /\b(?:api[-_ ]?key|credential|password|secret|token)\b/i,
  },
  {
    label: "machine identifier",
    pattern: /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
  },
];

function fail(path, message) {
  throw new TypeError(`${path}: ${message}`);
}

function assertObject(value, path) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "expected an object");
  }
}

function assertArray(value, path, maximum) {
  if (!Array.isArray(value)) fail(path, "expected an array");
  if (value.length > maximum) fail(path, `must contain at most ${maximum} records`);
}

function assertKeys(value, allowed, required, path) {
  assertObject(value, path);
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  const missing = required.filter((key) => !(key in value));
  if (unknown.length > 0) fail(path, `contains unsupported keys: ${unknown.join(", ")}`);
  if (missing.length > 0) fail(path, `is missing required keys: ${missing.join(", ")}`);
}

function assertString(value, path, maximum = 240) {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    fail(path, `expected a non-empty string no longer than ${maximum} characters`);
  }
}

function assertIdentifier(value, path) {
  assertString(value, path, 64);
  if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,63}$/.test(value)) {
    fail(path, "expected an alphanumeric, hyphen-safe identifier");
  }
}

function assertEnum(value, allowed, path) {
  if (!allowed.has(value)) fail(path, `unsupported value ${JSON.stringify(value)}`);
}

function assertNumber(value, path, { positive = false } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    fail(path, "expected a finite, non-negative number");
  }
  if (positive && value === 0) fail(path, "expected a number greater than zero");
}

function assertInteger(value, path, { positive = false, maximum } = {}) {
  assertNumber(value, path, { positive });
  if (!Number.isInteger(value)) fail(path, "expected an integer");
  if (maximum !== undefined && value > maximum) {
    fail(path, `must be no greater than ${maximum}`);
  }
}

function assertRecordBase(record, path) {
  assertIdentifier(record.id, `${path}.id`);
  assertString(record.title, `${path}.title`, 120);
  assertString(record.detail, `${path}.detail`);
  assertEnum(record.exposure, exposures, `${path}.exposure`);
  assertEnum(record.verification, verifications, `${path}.verification`);
  if (record.exposure === "local-only" && record.verification !== "verified") {
    fail(path, "local-only records require verified verification");
  }
}

function assertQueueRecord(record, path) {
  assertKeys(record, queueKeys, queueRequiredKeys, path);
  assertRecordBase(record, path);
  assertEnum(record.state, queueStates, `${path}.state`);
  const hasCompleted = "completedSteps" in record;
  const hasTotal = "totalSteps" in record;
  if (hasCompleted !== hasTotal) {
    fail(path, "completedSteps and totalSteps must be supplied together");
  }
  if (hasCompleted) {
    assertInteger(record.completedSteps, `${path}.completedSteps`, { maximum: 100000 });
    assertInteger(record.totalSteps, `${path}.totalSteps`, {
      positive: true,
      maximum: 100000,
    });
    if (record.completedSteps > record.totalSteps) {
      fail(path, "completedSteps cannot exceed totalSteps");
    }
  }
  if ("currentStep" in record) assertString(record.currentStep, `${path}.currentStep`, 120);
  if ("lastActiveSeconds" in record) {
    assertInteger(record.lastActiveSeconds, `${path}.lastActiveSeconds`, {
      maximum: 315360000,
    });
  }
  if ("memoryMB" in record) {
    assertNumber(record.memoryMB, `${path}.memoryMB`);
    if (record.memoryMB > 16777216) fail(`${path}.memoryMB`, "is outside the supported range");
  }
  if ("cpuPercent" in record) {
    assertNumber(record.cpuPercent, `${path}.cpuPercent`);
    if (record.cpuPercent > 100) fail(`${path}.cpuPercent`, "must be no greater than 100");
  }
}

function assertTestRecord(record, path) {
  assertKeys(record, testKeys, testKeys, path);
  assertRecordBase(record, path);
  assertEnum(record.result, testResults, `${path}.result`);
}

function assertResourceBudgetRecord(record, path) {
  assertKeys(record, budgetKeys, budgetRequiredKeys, path);
  assertRecordBase(record, path);
  assertString(record.displayValue, `${path}.displayValue`, 80);
  if ("value" in record) assertNumber(record.value, `${path}.value`);
  if ("capacity" in record) assertNumber(record.capacity, `${path}.capacity`, { positive: true });
}

function assertSignalRecord(record, path) {
  assertKeys(record, signalKeys, signalKeys, path);
  assertRecordBase(record, path);
  assertEnum(record.state, signalStates, `${path}.state`);
}

function allRecords(snapshot) {
  return [
    ...snapshot.queue,
    ...snapshot.tests,
    ...snapshot.resourceBudget,
    ...snapshot.signals,
  ];
}

function assertSanitized(snapshot, path) {
  allRecords(snapshot).forEach((record, index) => {
    if (record.exposure !== "sanitized") {
      fail(`${path}.records[${index}]`, "this snapshot mode permits sanitized records only");
    }
  });
}

export function assertDashboardSnapshot(snapshot, { surface = "native" } = {}) {
  assertKeys(snapshot, rootKeys, rootKeys, "snapshot");
  if (snapshot.schemaVersion !== "1.0") {
    fail("snapshot.schemaVersion", "expected version 1.0");
  }
  assertEnum(snapshot.mode, modes, "snapshot.mode");

  assertArray(snapshot.queue, "snapshot.queue", 100);
  snapshot.queue.forEach((record, index) =>
    assertQueueRecord(record, `snapshot.queue[${index}]`),
  );

  assertArray(snapshot.tests, "snapshot.tests", 100);
  snapshot.tests.forEach((record, index) =>
    assertTestRecord(record, `snapshot.tests[${index}]`),
  );

  assertArray(snapshot.resourceBudget, "snapshot.resourceBudget", 50);
  snapshot.resourceBudget.forEach((record, index) =>
    assertResourceBudgetRecord(record, `snapshot.resourceBudget[${index}]`),
  );

  assertArray(snapshot.signals, "snapshot.signals", 100);
  snapshot.signals.forEach((record, index) =>
    assertSignalRecord(record, `snapshot.signals[${index}]`),
  );

  if (snapshot.mode !== "local") assertSanitized(snapshot, "snapshot");

  if (surface === "web") {
    if (snapshot.mode !== "sanitized-remote") {
      fail("snapshot.mode", "the web surface requires sanitized-remote mode");
    }
    assertSanitized(snapshot, "snapshot");
  } else if (surface !== "native") {
    fail("surface", `unsupported surface ${JSON.stringify(surface)}`);
  }

  return snapshot;
}

function visitStrings(value, path, visitor) {
  if (typeof value === "string") {
    visitor(value, path);
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => visitStrings(item, `${path}[${index}]`, visitor));
  } else if (value !== null && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => visitStrings(item, `${path}.${key}`, visitor));
  }
}

export function assertPrivacyNeutralSnapshot(snapshot) {
  visitStrings(snapshot, "snapshot", (value, path) => {
    if (path === "snapshot.schemaVersion") return;
    for (const { label, pattern } of privatePatterns) {
      if (pattern.test(value)) fail(path, `contains a forbidden ${label}`);
    }
  });
  return snapshot;
}
