// Storyboard harness — drives the live splash page, captures screenshots, and
// renders a planned-vs-implemented doc from manifest.json. The harness IS the
// canonical "what's implemented" source: regenerating docs/STORYBOARD.md on
// every run keeps planned-vs-implemented from going stale. Add a step by
// navigating and calling shot('NN-name'), then reference the PNG in manifest.json.

import { chromium } from "playwright";
import fs from "node:fs";

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:5173";
const OUT = process.env.OUT_DIR ?? "/out";
const DOCS = process.env.DOCS_DIR ?? "/docs"; // ./docs mounted by the compose storyboard service
const MANIFEST = process.env.MANIFEST ?? "manifest.json";

fs.mkdirSync(OUT, { recursive: true });

// Render docs/STORYBOARD.md from the manifest + whatever shots exist on disk.
// Copies the captured shots into docs/assets/storyboard/ (COMMITTED) so the
// previews render inline on GitHub (a CI artifact zip can't be embedded in md).
function generateStoryboard() {
  if (!fs.existsSync(MANIFEST)) return console.log("storyboard: no manifest, skipped");
  let m;
  try { m = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); }
  catch (e) { return console.log("storyboard: bad manifest — " + e.message); }
  if (!fs.existsSync(DOCS)) return console.log("storyboard: no /docs mount, skipped doc render");

  const emoji = { done: "✅", partial: "🚧", planned: "⬜", changed: "🔄" };
  const counts = { done: 0, partial: 0, planned: 0, changed: 0 };
  const exists = (s) => s && fs.existsSync(`${OUT}/${s}`);
  const esc = (s) => (s || "").replace(/\|/g, "\\|");
  const assetsDir = `${DOCS}/assets/storyboard`;
  fs.mkdirSync(assetsDir, { recursive: true });

  const head = [
    "# {{ project_name }} — Storyboard (planned vs implemented)",
    "",
    "> **Auto-generated** by the e2e screenshot harness (`storyboard/storyboard.mjs`)",
    "> from `storyboard/manifest.json`. Don't edit by hand — run `make storyboard`",
    "> to refresh the screenshots and this file. Previews are committed under",
    "> `docs/assets/storyboard/` so they render here on GitHub.",
    "",
    "**Legend:** ✅ Implemented · 🚧 Partial / externally blocked · ⬜ Planned · 🔄 Changed / simplified",
    "",
  ];

  const body = [];
  for (const v of m.versions || []) {
    body.push("---", "", `## ${v.title}`);
    if (v.subtitle) body.push("", `_${v.subtitle}_`);
    for (const g of v.groups || []) {
      body.push("", `### ${g.name}`, "",
        "| Screen | Preview | Status | Story | Notes |", "|---|---|---|---|---|");
      for (const r of g.rows || []) {
        if (counts[r.status] !== undefined) counts[r.status]++;
        let preview = "—";
        if (r.shot) {
          if (exists(r.shot)) {
            fs.copyFileSync(`${OUT}/${r.shot}`, `${assetsDir}/${r.shot}`);
            preview = `<img src="assets/storyboard/${r.shot}" width="150">`;
          } else if (r.status === "done") preview = "⚠️ _shot missing_";
        }
        body.push(`| ${esc(r.screen)} | ${preview} | ${emoji[r.status] || ""} ${r.status} `
          + `| ${esc(r.story) || "—"} | ${esc(r.note)} |`);
      }
    }
    body.push("");
  }

  const summary = `**Status:** ✅ ${counts.done} done · 🚧 ${counts.partial} partial · `
    + `⬜ ${counts.planned} planned · 🔄 ${counts.changed} changed`;
  const out = [...head, summary, "", ...body].join("\n") + "\n";
  try {
    fs.writeFileSync(`${DOCS}/STORYBOARD.md`, out);
    console.log(`📄 storyboard → docs/STORYBOARD.md `
      + `(${counts.done}✅ ${counts.partial}🚧 ${counts.planned}⬜ ${counts.changed}🔄)`);
  } catch (e) { console.log("storyboard write failed: " + e.message); }
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });

async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`captured ${name}.png`);
}

// Hard assertions — once a screen is stable, assert its key content so a
// regression fails the run (and the Storyboard check). Failures are collected so
// every step still runs and the doc still renders; the run exits non-zero at the
// end. Promote the Storyboard workflow to a required check in auto-merge.yml when
// you want these to block merges.
const failures = [];
function assert(label, ok) {
  if (ok) { console.log(`✓ assert: ${label}`); }
  else { failures.push(label); console.error(`✗ assert: ${label}`); }
}

try {
  let ready = false;
  for (let i = 0; i < 30 && !ready; i++) {
    try { ready = (await page.request.get(FRONTEND_URL)).ok(); }
    catch { /* not up yet */ }
    if (!ready) await page.waitForTimeout(2000);
  }
  if (!ready) throw new Error(`splash not reachable at ${FRONTEND_URL}`);

  await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
  await shot("01-landing");
  const heading = (await page.locator("h1").first().textContent().catch(() => "")) || "";
  assert("landing renders the project name in <h1>", heading.includes("{{ project_name }}"));
} catch (e) {
  console.error("storyboard error: " + e.message);
  process.exitCode = 1;
} finally {
  generateStoryboard();
  await browser.close();
  if (failures.length) {
    process.exitCode = 1;
    console.error(`storyboard: ${failures.length} assertion(s) failed: ${failures.join(", ")}`);
  }
  console.log(`storyboard complete → ${OUT}`);
}
