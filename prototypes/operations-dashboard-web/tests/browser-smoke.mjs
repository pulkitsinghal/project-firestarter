import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, stat } from "node:fs/promises";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const root = resolve(fileURLToPath(new URL("../", import.meta.url)));
const fixture = JSON.parse(
  await readFile(join(root, "fixtures", "sanitized-remote.snapshot.json"), "utf8"),
);
const evidenceDirectory = process.env.EVIDENCE_DIR
  ? resolve(process.env.EVIDENCE_DIR)
  : null;
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

function startServer() {
  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(
          request.url ?? "/",
          ["http:", "", "test", "invalid"].join("/"),
        ).pathname,
      );
      const requested = pathname === "/" ? "/index.html" : pathname;
      const file = resolve(root, `.${requested}`);
      if (file !== root && !file.startsWith(`${root}${sep}`)) {
        response.writeHead(403).end("Forbidden");
        return;
      }
      if (!(await stat(file)).isFile()) throw new Error("Not a file");
      response.writeHead(200, {
        "content-type": contentTypes[extname(file)] ?? "application/octet-stream",
        "cache-control": "no-store",
      });
      response.end(await readFile(file));
    } catch {
      response.writeHead(404).end("Not found");
    }
  });
  return new Promise((resolveListening) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const loopback = ["127", "0", "0", "1"].join(".");
      resolveListening({
        server,
        baseURL: `${["http:", "", loopback].join("/")}:${address.port}`,
      });
    });
  });
}

async function stopServer(server) {
  await new Promise((resolveClosed, rejectClosed) => {
    server.close((error) => error ? rejectClosed(error) : resolveClosed());
  });
}

async function capture(page, name) {
  if (!evidenceDirectory) return;
  await page.screenshot({
    path: join(evidenceDirectory, name),
    fullPage: true,
  });
}

async function waitForRendered(page) {
  const status = page.locator("#snapshot-status");
  await status.waitFor({ state: "attached", timeout: 5_000 });
  await page.waitForFunction(
    () => document.querySelector("#snapshot-status")?.textContent !== "Loading supplied snapshot…",
    undefined,
    { timeout: 5_000 },
  );
  const statusText = await status.textContent();
  const errorText = await page.locator("#error").textContent();
  assert.equal(
    statusText,
    "Published snapshot rendered.",
    `unexpected page status; error=${JSON.stringify(errorText)}`,
  );
}

async function assertNoHorizontalOverflow(page) {
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    true,
  );
}

const { server, baseURL } = await startServer();
if (evidenceDirectory) await mkdir(evidenceDirectory, { recursive: true });
const browser = await chromium.launch();

try {
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(baseURL);
    await waitForRendered(page);

    assert.equal(await page.locator(".portfolio-lane").count(), 10);
    assert.equal(await page.locator("#queue-count").textContent(), "10 lanes");
    assert.equal(await page.locator(".portfolio-lane.state-running").count(), 2);
    assert.equal(await page.locator(".portfolio-lane.state-queued").count(), 3);
    assert.equal(await page.locator(".portfolio-lane.state-waiting").count(), 2);
    assert.equal(await page.locator(".portfolio-lane.state-ready").count(), 3);
    assert.equal(await page.getByText("not run", { exact: true }).count(), 1);
    assert.ok(await page.getByText("not implemented", { exact: true }).count() >= 1);
    assert.ok(await page.getByText("unavailable", { exact: true }).count() >= 1);
    assert.equal(await page.locator('[role="meter"]').count(), 0);
    assert.equal(await page.locator(".resource-missing").count(), 5);
    assert.equal(await page.locator("h1").count(), 1);
    assert.equal(
      await page.evaluate(() => (
        [...document.querySelectorAll("section[aria-labelledby]")].every(
          (section) => document.getElementById(section.getAttribute("aria-labelledby")),
        )
      )),
      true,
    );
    await assertNoHorizontalOverflow(page);
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(pageErrors, []);
    await page.close();
  }

  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await page.goto(baseURL);
    await waitForRendered(page);

    assert.equal(await page.locator(".portfolio-lane").count(), 10);
    assert.equal(await page.locator(".resource-card").count(), 5);
    await assertNoHorizontalOverflow(page);
    await page.close();
  }

  {
    const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
    await page.route("**/fixtures/sanitized-remote.snapshot.json", (route) => {
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ...fixture, mode: "local" }),
      });
    });
    await page.goto(baseURL);
    await page.locator("#error").waitFor({ state: "visible" });

    assert.match(
      await page.locator("#error").textContent(),
      /The web renderer accepts sanitized-remote snapshots only/,
    );
    assert.equal(
      await page.locator("#snapshot-status").textContent(),
      "Snapshot could not be rendered.",
    );
    assert.equal(await page.locator("#dashboard-content").isHidden(), true);
    assert.equal(await page.locator(".portfolio-lane").count(), 0);
    await capture(page, "invalid-snapshot.png");
    await page.close();
  }

  {
    const page = await browser.newPage({ viewport: { width: 320, height: 760 } });
    const maximumText = structuredClone(fixture);
    maximumText.queue[0].title = "A".repeat(120);
    maximumText.queue[0].detail = "B".repeat(240);
    maximumText.resourceBudget[0].displayValue = "9".repeat(80);
    await page.route("**/fixtures/sanitized-remote.snapshot.json", (route) => {
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(maximumText),
      });
    });
    await page.goto(baseURL);
    await waitForRendered(page);

    await assertNoHorizontalOverflow(page);
    await page.close();
  }

  {
    const page = await browser.newPage();
    const injectedTitle = '<img src="x" onerror="globalThis.__dashboardXss = true">';
    const injected = structuredClone(fixture);
    injected.queue[0].title = injectedTitle;
    await page.route("**/fixtures/sanitized-remote.snapshot.json", (route) => {
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(injected),
      });
    });
    await page.goto(baseURL);
    await waitForRendered(page);

    assert.equal(
      await page.locator(".portfolio-lane h3").first().textContent(),
      injectedTitle,
    );
    assert.equal(await page.locator(".portfolio-lane img").count(), 0);
    assert.equal(
      await page.evaluate(() => globalThis.__dashboardXss),
      undefined,
    );
    await page.close();
  }

  {
    const page = await browser.newPage();
    const empty = {
      ...fixture,
      queue: [],
      tests: [],
      resourceBudget: [],
      signals: [],
    };
    await page.route("**/fixtures/sanitized-remote.snapshot.json", (route) => {
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(empty),
      });
    });
    await page.goto(baseURL);
    await waitForRendered(page);

    assert.equal(await page.locator(".empty-state").count(), 4);
    assert.deepEqual(
      await page.locator(".empty-state").allTextContents(),
      [
        "No sanitized resource records were supplied.",
        "No sanitized lifecycle records were supplied.",
        "No sanitized records were supplied.",
        "No sanitized records were supplied.",
      ],
    );
    await page.close();
  }

  process.stdout.write("Browser smoke: 6 scenarios passed.\n");
} finally {
  await browser.close();
  await stopServer(server);
}
