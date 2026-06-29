// Storyboard harness — drives the live app and captures a sequence of
// screenshots that document the core flow. Runs headless against the frontend
// service. Add a step by navigating and calling shot('name').

import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:{{ port_web }}";
const OUT = process.env.OUT_DIR ?? "/out";

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });

// Wait for the app (and its backend proxy) to be reachable.
let ready = false;
for (let i = 0; i < 30 && !ready; i++) {
  try {
    const r = await page.request.get(`${FRONTEND_URL}/api/items`);
    ready = r.ok();
  } catch {
    /* not up yet */
  }
  if (!ready) await page.waitForTimeout(2000);
}
if (!ready) {
  console.error(`app not reachable at ${FRONTEND_URL}`);
  process.exit(1);
}

async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`captured ${name}.png`);
}

// 1. Landing — home page with the items list.
await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });
await shot("01-landing");

await browser.close();
console.log(`storyboard complete → ${OUT}`);
