import fs from "node:fs";
import { chromium } from "playwright";

const APP_URL = process.env.APP_URL ?? "http://localhost:{{ port_web }}";
const OUT = process.env.OUT_DIR ?? "/out";
const DOCS = process.env.DOCS_DIR ?? "/docs";
const MANIFEST = "manifest.json";

fs.mkdirSync(OUT, { recursive: true });

function generateStoryboard() {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
  const assetsDir = `${DOCS}/assets/storyboard`;
  fs.mkdirSync(assetsDir, { recursive: true });

  const emoji = { done: "✅", partial: "🚧", planned: "⬜", changed: "🔄" };
  const counts = { done: 0, partial: 0, planned: 0, changed: 0 };
  const escapeCell = (value = "") => value.replace(/\|/g, "\\|");
  const lines = [
    "# {{ project_name }} — Storyboard (planned vs implemented)",
    "",
    "> Auto-generated from real screenshots by `make storyboard`. The manifest",
    "> is the plan; the assertions and rebuilt app are the implementation evidence.",
    "",
    "**Legend:** ✅ Implemented · 🚧 Partial / externally blocked · ⬜ Planned · 🔄 Changed / simplified",
    "",
  ];

  for (const version of manifest.versions ?? []) {
    lines.push("---", "", `## ${version.title}`, "");
    if (version.subtitle) lines.push(`_${version.subtitle}_`, "");
    for (const group of version.groups ?? []) {
      lines.push(
        `### ${group.name}`,
        "",
        "| Screen | Preview | Status | Story | Notes |",
        "|---|---|---|---|---|",
      );
      for (const row of group.rows ?? []) {
        if (counts[row.status] !== undefined) counts[row.status] += 1;
        let preview = "—";
        if (row.shot) {
          const source = `${OUT}/${row.shot}`;
          if (fs.existsSync(source)) {
            fs.copyFileSync(source, `${assetsDir}/${row.shot}`);
            preview = `<img src="assets/storyboard/${row.shot}" width="180">`;
          } else if (row.status === "done") {
            preview = "⚠️ _shot missing_";
          }
        }
        lines.push(
          `| ${escapeCell(row.screen)} | ${preview} | ${emoji[row.status] ?? ""} ${row.status} | `
          + `${escapeCell(row.story)} | ${escapeCell(row.note)} |`,
        );
      }
      lines.push("");
    }
  }

  lines.splice(
    7,
    0,
    `**Status:** ✅ ${counts.done} done · 🚧 ${counts.partial} partial · `
      + `⬜ ${counts.planned} planned · 🔄 ${counts.changed} changed`,
    "",
  );
  fs.writeFileSync(`${DOCS}/STORYBOARD.md`, `${lines.join("\n")}\n`);
  console.log(`storyboard → ${DOCS}/STORYBOARD.md`);
}

const failures = [];
function assert(label, condition) {
  if (condition) {
    console.log(`✓ ${label}`);
  } else {
    failures.push(label);
    console.error(`✗ ${label}`);
  }
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1080, height: 980 },
});
const page = await context.newPage();

async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`captured ${name}.png`);
}

async function reloadTasks() {
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(250);
}

try {
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await page.locator("#task-form").waitFor();
  await shot("01-ready");
  assert(
    "ready page names the generated project",
    (await page.locator("body").textContent()).includes("{{ project_name }}"),
  );

  await page.locator("#task-message").fill("Generate the synthetic handoff summary");
  const createResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/tasks")
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Run task" }).click();
  const createResponse = await createResponsePromise;
  assert("task creation returns 202", createResponse.status() === 202);
  const created = await createResponse.json();
  assert("task creation returns an opaque id", typeof created.taskId === "string");

  await page.locator(`[data-status]`).first().waitFor();
  await shot("02-in-flight");
  const inFlightStatus = await page.locator(`[data-status]`).first().getAttribute("data-status");
  assert(
    "created task renders a known lifecycle state",
    ["queued", "running", "completed"].includes(inFlightStatus),
  );

  await page.locator('[data-status="completed"]').waitFor({ timeout: 20000 });
  await shot("03-completed");
  assert(
    "completed result is reconciled from durable state",
    (await page.locator(".task__result").first().textContent()).includes(
      "Finished: Generate the synthetic handoff summary",
    ),
  );

  const ackResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/tasks/${created.taskId}/ack`)
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Mark seen" }).click();
  const ackResponse = await ackResponsePromise;
  assert("terminal acknowledgement succeeds", ackResponse.ok());

  await page.getByRole("button", { name: "Seen" }).waitFor();
  await shot("04-acknowledged");
  assert(
    "acknowledgement is visible after reload",
    (await page.locator(".task__ack").first().textContent()) === "Seen",
  );
} catch (error) {
  failures.push(error.message);
  console.error(`storyboard error: ${error.stack ?? error.message}`);
} finally {
  generateStoryboard();
  await browser.close();
}

if (failures.length > 0) {
  console.error(`storyboard failed: ${failures.join("; ")}`);
  process.exitCode = 1;
}
