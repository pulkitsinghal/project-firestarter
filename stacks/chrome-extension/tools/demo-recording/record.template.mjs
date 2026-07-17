// Demo/QA recorder TEMPLATE — capture the extension's REAL side panel (page +
// panel + cursor) as video, with no login and no backend.
//
// Copy this to `record.mjs` and fill the four CONFIGURE blocks for your app.
// Run it against the built extension (`make build` first):
//     node tools/demo-recording/record.mjs           # headed (works under Xvfb in CI)
//
// Why this shape (see README.md for the full rationale + gotchas):
//   * The side panel is a separate chrome-extension:// surface. Playwright's
//     per-page video records the tab, not the panel/cursor. So we IFRAME the
//     live sidebar.html into a staged host page — now it's ONE page and
//     Playwright `recordVideo` captures it reliably (x11grab of a bare Xvfb
//     gives black frames; don't go there).
//   * Auth/data are seeded offline into chrome.storage via the service worker,
//     so no network, no OTP, no real account is ever shown.
import { chromium } from 'playwright';
import http from 'http';
import { cpSync, readFileSync, writeFileSync, rmSync, existsSync, renameSync, readdirSync, mkdirSync } from 'fs';
import path from 'node:path';

const log = (...a) => console.log('[rec]', ...a);
setTimeout(() => { log('WATCHDOG — killing'); process.exit(1); }, 90_000).unref();

const HERE = path.dirname(new URL(import.meta.url).pathname);
const SRC = process.env.EXTENSION_PATH || path.resolve(HERE, '..', '..', 'extension', 'dist');
const EXT = path.join(HERE, '.ext-rec');   // sanitized copy of dist/ (gitignored)
const OUT = path.join(HERE, '.out');       // recordings + frames (gitignored)
mkdirSync(path.join(OUT, 'vid'), { recursive: true });

// --- sanitize a copy of dist/ (idempotent) ---
// Loading an unpacked MV3 build can trip on declarative_net_request rules
// (a blocking "Internal error while parsing rules" modal). Strip them for the
// demo, and pre-grant the fixture origin so no "allow this site" banner appears.
if (!existsSync(path.join(EXT, 'manifest.json'))) {
  cpSync(SRC, EXT, { recursive: true });
  const mf = JSON.parse(readFileSync(path.join(EXT, 'manifest.json'), 'utf8'));
  delete mf.declarative_net_request;
  mf.host_permissions = [...(mf.host_permissions || []), 'http://localhost:4180/*'];
  writeFileSync(path.join(EXT, 'manifest.json'), JSON.stringify(mf, null, 2));
  if (existsSync(path.join(EXT, 'rules.json'))) rmSync(path.join(EXT, 'rules.json'));
}

// Visible cursor overlay — injected via addInitScript (page CSP blocks addScriptTag).
const overlaySrc = readFileSync(path.join(HERE, 'visual_cursor_overlay.js'), 'utf8');
const cursorInit = `(()=>{const run=()=>{try{${overlaySrc}}catch(e){console.error('[overlay]',e)}};if(document.body){run()}else{document.addEventListener('DOMContentLoaded',run)}})()`;

// ── CONFIGURE 1: the offline auth/data seed ────────────────────────────────
// Mirror how your background auth check reads chrome.storage. Seed whatever
// makes the panel render "signed in" with demo content. Example shape:
const STORAGE_SEED = {
  // userId: 'demo-user',
  // authRecords: { 'demo-user': { token: '1', expiresAt: Date.now() + 7 * 864e5 } },
  // items: MOCK_ITEMS,
};

// ── CONFIGURE 2: network mocks (so no backend is needed) ───────────────────
const ROUTE_MOCKS = [
  // { pattern: /your-api-endpoint/, body: MOCK_ITEMS },
];

// ── CONFIGURE 3: the staged host page ──────────────────────────────────────
// A plain page that gives the panel realistic context. Use FICTIONAL brands so
// the clip is shareable. It must iframe the live panel by extension id.
function stage(extId) {
  return `<!doctype html><meta charset=utf-8>
<style>*{box-sizing:border-box}html,body{margin:0;height:100%}
.wrap{display:flex;height:100vh;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
.host{flex:1;padding:26px 38px;background:#fff}
.panel{width:430px;border-left:1px solid #cbd5e1}.panel iframe{width:100%;height:100%;border:0}
#demo-subtitle{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:rgba(17,24,39,.93);
 color:#fff;padding:12px 22px;border-radius:10px;font-size:17px;font-weight:600;opacity:0;transition:opacity .35s;
 z-index:2147483646;pointer-events:none}</style>
<div class=wrap>
  <div class=host><h1>Fictional Co · Demo</h1><p>Replace with a representative host page.</p></div>
  <div class=panel><iframe src="chrome-extension://${extId}/sidebar.html"></iframe></div>
</div><div id=demo-subtitle></div>`;
}

const ctx = await chromium.launchPersistentContext(path.join(OUT, 'prof'), {
  headless: false, channel: 'chromium',
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: path.join(OUT, 'vid'), size: { width: 1280, height: 800 } },
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
    `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, '--window-size=1280,800'],
});
for (const m of ROUTE_MOCKS) {
  await ctx.route(m.pattern, r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(m.body) })).catch(() => {});
}
// MV3 extension id = the hostname of its background service worker URL.
let [sw] = ctx.serviceWorkers();
if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 20_000 }).catch(() => null);
if (!sw) { log('NO SERVICE WORKER — extension failed to load'); await ctx.close(); process.exit(2); }
const extId = new URL(sw.url()).hostname;
await sw.evaluate((s) => chrome.storage.local.set(s), STORAGE_SEED).catch(() => {});

const server = http.createServer((_q, res) => { res.setHeader('content-type', 'text/html'); res.end(stage(extId)); });
await new Promise(r => server.listen(4180, r));
const page = ctx.pages()[0] || await ctx.newPage();
await page.addInitScript(cursorInit);
await page.goto('http://localhost:4180/', { waitUntil: 'domcontentloaded' }).catch(e => log('goto', e.message));

const fr = page.frameLocator('iframe');
const sub = (t) => page.evaluate((t) => { const s = document.getElementById('demo-subtitle'); if (s) { s.textContent = t; s.style.opacity = t ? '1' : '0'; } }, t).catch(() => {});
const cur = (x, y, d = 600) => page.evaluate(([x, y, d]) => window.demoVisualCursor?.moveTo(x, y, d), [x, y, d]).catch(() => {});
const shot = (n) => page.screenshot({ path: path.join(OUT, `frame-${n}.png`) }).catch(() => {}); // VERIFY BY LOOKING

await page.waitForTimeout(2200);
await page.evaluate(() => window.demoVisualCursor?.show()).catch(() => {});
await shot('checkpoint'); // open this PNG and confirm the panel actually rendered signed-in

// ── CONFIGURE 4: your scene beats ──────────────────────────────────────────
// Drive `fr.locator('#yourControl')`, narrate with sub('…'), move cur(x,y).
await sub('Your first beat.'); await page.waitForTimeout(2500);

await sub(''); await page.waitForTimeout(400);
server.close();
await ctx.close();
try { const f = readdirSync(path.join(OUT, 'vid')).filter(x => x.endsWith('.webm')).sort().pop(); if (f) renameSync(path.join(OUT, 'vid', f), path.join(OUT, 'scene.webm')); } catch (e) { log('rename', e.message); }
log('done — see .out/scene.webm (stitch with video_processor.py)');
process.exit(0);
