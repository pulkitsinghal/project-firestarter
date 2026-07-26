const EXPECTED_MODE = "sanitized-remote";
const RECORD_SECTIONS = ["queue", "tests", "resourceBudget", "signals"];
const ROOT_KEYS = ["schemaVersion", "mode", ...RECORD_SECTIONS];
const ALLOWED_EXPOSURES = new Set(["sanitized"]);
const ALLOWED_VERIFICATION = new Set(["verified", "estimated", "unavailable", "not-implemented"]);
const FORBIDDEN_FIELD_FRAGMENTS = ["endpoint", "url", "host", "ip", "path", "credential", "secret", "token"];
const RECORD_SPECS = {
  queue: {
    required: ["id", "title", "detail", "state", "exposure", "verification"],
    optional: [],
    stateKey: "state",
    states: new Set(["running", "queued", "waiting", "ready"]),
  },
  tests: {
    required: ["id", "title", "detail", "result", "exposure", "verification"],
    optional: [],
    stateKey: "result",
    states: new Set(["passed", "failed", "queued", "not-run", "not-implemented", "unknown"]),
  },
  resourceBudget: {
    required: ["id", "title", "detail", "displayValue", "exposure", "verification"],
    optional: ["value", "capacity"],
  },
  signals: {
    required: ["id", "title", "detail", "state", "exposure", "verification"],
    optional: [],
    stateKey: "state",
    states: new Set(["available", "attention", "unavailable", "unknown"]),
  },
};
const PRIVATE_VALUE_PATTERNS = [
  new RegExp(`\\b(?:h${"ttps?"}|${"file"}|${"ssh"}):` + "//", "i"),
  new RegExp(
    `\\b(?:${["local", "host"].join("")}|${["tail", "net"].join("")}|${["tail", "scale"].join("")})\\b`
      + `|\\.${"local"}\\b|\\.${"ts"}\\.${"net"}\\b`,
    "i",
  ),
  /\b(?:\d{1,3}\.){3}\d{1,3}\b/,
  /\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\b/i,
  new RegExp(`/${"Users"}/|/${"home"}/|[A-Za-z]:\\\\`),
  /\b[^@\s]+@[^@\s]+\.[^@\s]+\b/,
  new RegExp(`\\b(?:api[-_ ]?key|${"credential"}|password|${"secret"}|${"token"})\\b`, "i"),
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
];

function text(tag, value, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = String(value ?? "");
  return element;
}

function walk(value, visit) {
  if (Array.isArray(value)) {
    value.forEach((item) => walk(item, visit));
    return;
  }
  if (!value || typeof value !== "object") return;
  Object.entries(value).forEach(([key, child]) => {
    visit(key, child);
    walk(child, visit);
  });
}

function fail(message) {
  throw new Error(message);
}

function assertExactKeys(value, required, optional, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`${path} must be an object.`);
  }
  const allowed = new Set([...required, ...optional]);
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  const missing = required.filter((key) => !(key in value));
  if (unknown.length) fail(`${path} has unsupported fields: ${unknown.join(", ")}.`);
  if (missing.length) fail(`${path} is missing fields: ${missing.join(", ")}.`);
}

function assertText(value, maximum, path) {
  if (typeof value !== "string" || !value.length || value.length > maximum) {
    fail(`${path} must be a non-empty string no longer than ${maximum} characters.`);
  }
}

function assertPrivacyNeutralValues(record, path) {
  walk(record, (key, value) => {
    if (typeof value !== "string") return;
    if (PRIVATE_VALUE_PATTERNS.some((pattern) => pattern.test(value))) {
      fail(`${path}.${key} contains private-looking content.`);
    }
  });
}

function assertRecord(section, record, index) {
  const path = `${section}[${index}]`;
  const spec = RECORD_SPECS[section];
  assertExactKeys(record, spec.required, spec.optional, path);
  assertText(record.id, 64, `${path}.id`);
  if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,63}$/.test(record.id)) {
    fail(`${path}.id is not a safe identifier.`);
  }
  assertText(record.title, 120, `${path}.title`);
  assertText(record.detail, 240, `${path}.detail`);

  if (!ALLOWED_EXPOSURES.has(record.exposure)) {
    fail(`Non-sanitized record rejected: ${record.id || "unknown"}`);
  }
  if (!ALLOWED_VERIFICATION.has(record.verification)) {
    fail(`Unknown verification status: ${record.verification || "missing"}`);
  }
  if (spec.stateKey && !spec.states.has(record[spec.stateKey])) {
    fail(`${path}.${spec.stateKey} has an unsupported value.`);
  }
  if (section === "resourceBudget") {
    assertText(record.displayValue, 80, `${path}.displayValue`);
    if (
      ("value" in record && (!Number.isFinite(record.value) || record.value < 0))
      || (
        "capacity" in record
        && (!Number.isFinite(record.capacity) || record.capacity <= 0)
      )
    ) {
      fail(`${path} has an invalid numeric resource value.`);
    }
  }
  assertPrivacyNeutralValues(record, path);
}

export function assertSanitizedSnapshot(snapshot) {
  assertExactKeys(snapshot, ROOT_KEYS, [], "snapshot");
  if (snapshot.schemaVersion !== "1.0" || snapshot.mode !== EXPECTED_MODE) {
    throw new Error("The web renderer accepts sanitized-remote snapshots only.");
  }

  walk(snapshot, (key) => {
    const normalized = key.toLowerCase();
    if (FORBIDDEN_FIELD_FRAGMENTS.some((fragment) => normalized.includes(fragment))) {
      throw new Error(`Forbidden field in sanitized snapshot: ${key}`);
    }
  });

  for (const section of RECORD_SECTIONS) {
    if (!Array.isArray(snapshot[section])) {
      throw new Error(`Missing record collection: ${section}`);
    }
    const maximum = section === "resourceBudget" ? 50 : 100;
    if (snapshot[section].length > maximum) {
      fail(`${section} exceeds its record limit.`);
    }
    snapshot[section].forEach((record, index) => assertRecord(section, record, index));
  }
  return snapshot;
}

function chip(label, className) {
  return text("span", label, `chip ${className}`);
}

function recordCard(record, extraLabel) {
  const article = document.createElement("article");
  article.className = "record";
  const head = document.createElement("div");
  head.className = "record-head";
  head.append(text("h3", record.title));
  if (extraLabel) head.append(chip(extraLabel, record.verification));
  article.append(head, text("p", record.detail));

  const meta = document.createElement("div");
  meta.className = "record-meta";
  meta.append(
    chip(record.verification.replace("-", " "), record.verification),
    chip(record.exposure.replace("-", " "), record.exposure),
  );
  article.append(meta);
  return article;
}

function renderResources(records) {
  const root = document.querySelector("#resource-grid");
  root.replaceChildren();
  records.forEach((record) => {
    const article = document.createElement("article");
    article.className = "resource-card";
    article.append(text("span", record.title, "record-kicker"));

    const value = document.createElement("div");
    value.className = "resource-value";
    value.append(text("strong", record.displayValue));
    article.append(value);

    if (Number.isFinite(record.value) && Number.isFinite(record.capacity) && record.capacity > 0) {
      const meter = document.createElement("div");
      meter.className = "meter";
      meter.setAttribute("role", "meter");
      meter.setAttribute("aria-label", `${record.title}: ${record.displayValue}`);
      meter.setAttribute("aria-valuemin", "0");
      meter.setAttribute("aria-valuemax", String(record.capacity));
      meter.setAttribute("aria-valuenow", String(record.value));
      const fill = document.createElement("span");
      fill.style.width = `${Math.min(100, Math.round((record.value / record.capacity) * 100))}%`;
      meter.append(fill);
      article.append(meter);
    }
    article.append(text("p", record.detail));
    const meta = document.createElement("div");
    meta.className = "record-meta";
    meta.append(
      chip(record.verification.replace("-", " "), record.verification),
      chip(record.exposure.replace("-", " "), record.exposure),
    );
    article.append(meta);
    root.append(article);
  });
}

function renderQueue(records) {
  const root = document.querySelector("#queue-grid");
  root.replaceChildren();
  const labels = { running: "Running", queued: "Queued", waiting: "Waiting", ready: "Ready" };
  Object.entries(labels).forEach(([state, label]) => {
    const items = records.filter((record) => record.state === state);
    if (!items.length) return;
    const lane = document.createElement("section");
    lane.className = "lane";
    lane.setAttribute("aria-label", label);
    const heading = document.createElement("div");
    heading.className = "lane-header";
    heading.append(text("h2", label), text("span", items.length));
    lane.append(heading);
    const list = document.createElement("div");
    list.className = "record-list";
    items.forEach((record) => list.append(recordCard(record)));
    lane.append(list);
    root.append(lane);
  });
}

function renderList(selector, countSelector, records, labelFor) {
  const root = document.querySelector(selector);
  root.replaceChildren();
  records.forEach((record) => root.append(recordCard(record, labelFor(record))));
  document.querySelector(countSelector).textContent = `${records.length} records`;
}

export function renderSnapshot(snapshot) {
  assertSanitizedSnapshot(snapshot);
  renderResources(snapshot.resourceBudget);
  renderQueue(snapshot.queue);
  renderList("#tests-list", "#tests-count", snapshot.tests, (record) => record.result.replace("-", " "));
  renderList("#signals-list", "#signals-count", snapshot.signals, (record) => record.state);
}

async function loadFixture() {
  const response = await fetch("./fixtures/sanitized-remote.snapshot.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Fixture request failed: ${response.status}`);
  renderSnapshot(await response.json());
}

if (typeof document !== "undefined") {
  loadFixture().catch((error) => {
    const banner = document.querySelector("#error");
    banner.hidden = false;
    banner.textContent = `Snapshot unavailable: ${error.message}`;
  });
}
