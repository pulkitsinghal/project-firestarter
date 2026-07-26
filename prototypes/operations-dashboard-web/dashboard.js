const EXPECTED_MODE = "sanitized-remote";
const RECORD_SECTIONS = ["queue", "tests", "resourceBudget", "signals"];
const ALLOWED_EXPOSURES = new Set(["sanitized"]);
const ALLOWED_VERIFICATION = new Set(["verified", "estimated", "unavailable", "not-implemented"]);
const FORBIDDEN_FIELD_FRAGMENTS = ["endpoint", "url", "host", "ip", "path", "credential", "secret", "token"];

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

function assertSanitizedSnapshot(snapshot) {
  if (!snapshot || snapshot.mode !== EXPECTED_MODE) {
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
    for (const record of snapshot[section]) {
      if (!ALLOWED_EXPOSURES.has(record.exposure)) {
        throw new Error(`Non-sanitized record rejected: ${record.id || "unknown"}`);
      }
      if (!ALLOWED_VERIFICATION.has(record.verification)) {
        throw new Error(`Unknown verification status: ${record.verification || "missing"}`);
      }
    }
  }
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

function renderSnapshot(snapshot) {
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

loadFixture().catch((error) => {
  const banner = document.querySelector("#error");
  banner.hidden = false;
  banner.textContent = `Snapshot unavailable: ${error.message}`;
});
