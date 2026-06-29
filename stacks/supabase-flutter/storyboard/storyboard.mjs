// Storyboard harness — drives the live splash page and captures screenshots.
// Runs headless against the splash service. Add a step by navigating and
// calling shot('name').

import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:5173";
const OUT = process.env.OUT_DIR ?? "/out";

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });

// Wait for the page to be reachable.
let ready = false;
for (let i = 0; i < 30 && !ready; i++) {
  try {
    const r = await page.request.get(FRONTEND_URL);
    ready = r.ok();
  } catch {
    /* not up yet */
  }
  if (!ready) await page.waitForTimeout(2000);
}
if (!ready) {
  console.error(`splash not reachable at ${FRONTEND_URL}`);
  process.exit(1);
}

async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`captured ${name}.png`);
}

await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
await shot("01-landing");

await browser.close();
console.log(`storyboard complete → ${OUT}`);
