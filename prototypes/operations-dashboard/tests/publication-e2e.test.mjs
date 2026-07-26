import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createReadStream } from "node:fs";
import { lstat, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, normalize, resolve, sep } from "node:path";
import { promisify } from "node:util";
import test from "node:test";

const execFileAsync = promisify(execFile);
const commandPath = new URL("../bin/publish-sanitized.mjs", import.meta.url);

function localSnapshot(label) {
  const shared = { exposure: "sanitized", verification: "verified" };
  const local = { exposure: "local-only", verification: "verified" };
  return {
    schemaVersion: "1.0",
    mode: "local",
    queue: [
      {
        id: "SAFE-Q1",
        title: `${label} release`,
        detail: "Approved generic queue information.",
        state: "ready",
        ...shared,
      },
      {
        id: "LOCAL-Q1",
        title: "Local native record",
        detail: "This record must never reach the web bundle.",
        state: "running",
        ...local,
      },
    ],
    tests: [
      {
        id: "SAFE-T1",
        title: "Publication workflow",
        detail: "The generic workflow passed locally.",
        result: "passed",
        ...shared,
      },
    ],
    resourceBudget: [
      {
        id: "SAFE-R1",
        title: "Heavy validation lane",
        detail: "One bounded workflow at a time.",
        displayValue: "Available",
        ...shared,
      },
    ],
    signals: [
      {
        id: "SAFE-S1",
        title: "Snapshot availability",
        detail: "No machine measurement is included.",
        state: "available",
        ...shared,
      },
    ],
  };
}

async function runCLI(...argumentsToPass) {
  const { stdout, stderr } = await execFileAsync(
    process.execPath,
    [commandPath.pathname, ...argumentsToPass],
    { encoding: "utf8" },
  );
  assert.equal(stderr, "");
  return JSON.parse(stdout);
}

async function serve(directory) {
  const root = resolve(directory);
  const loopback = ["127", "0", "0", "1"].join(".");
  const server = createServer(async (request, response) => {
    const requestPath = request.url === "/" ? "/index.html" : request.url;
    const decoded = decodeURIComponent(requestPath.split("?")[0]);
    const candidate = resolve(root, `.${normalize(decoded)}`);
    if (!candidate.startsWith(`${root}${sep}`)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const info = await lstat(candidate);
      if (!info.isFile()) throw new Error("not a file");
      const contentTypes = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "text/javascript",
        ".json": "application/json",
      };
      response.writeHead(200, {
        "content-type": contentTypes[extname(candidate)] ?? "application/octet-stream",
      });
      createReadStream(candidate).pipe(response);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolveListening) => server.listen(0, loopback, resolveListening));
  const address = server.address();
  return {
    origin: ["http:", "/", "/", loopback, ":", address.port].join(""),
    close: () => new Promise((resolveClosed) => server.close(resolveClosed)),
  };
}

test("local input publishes, serves, updates, and rolls back end to end", async () => {
  const directory = await mkdtemp(join(tmpdir(), "operations-publication-e2e-"));
  const inputPath = join(directory, "input.json");
  const outputRoot = join(directory, "publication");
  try {
    await writeFile(inputPath, JSON.stringify(localSnapshot("First")), "utf8");
    const first = await runCLI(
      "build",
      "--input",
      inputPath,
      "--output-root",
      outputRoot,
    );
    assert.match(first.releaseId, /^[a-f0-9]{64}$/);
    assert.deepEqual(
      await runCLI(
        "verify",
        "--output-root",
        outputRoot,
        "--release-id",
        first.releaseId,
      ),
      { releaseId: first.releaseId, verified: true },
    );
    assert.equal(
      (await runCLI(
        "activate",
        "--output-root",
        outputRoot,
        "--release-id",
        first.releaseId,
      )).changed,
      true,
    );

    const web = await serve(join(outputRoot, "current"));
    try {
      const indexResponse = await fetch(`${web.origin}/`);
      assert.equal(indexResponse.status, 200);
      assert.match(await indexResponse.text(), /Operational Snapshot/);

      const rendererResponse = await fetch(`${web.origin}/dashboard.js`);
      assert.equal(rendererResponse.status, 200);
      assert.match(await rendererResponse.text(), /assertSanitizedSnapshot/);

      const snapshotResponse = await fetch(
        `${web.origin}/fixtures/sanitized-remote.snapshot.json`,
      );
      assert.equal(snapshotResponse.status, 200);
      const publishedSnapshot = await snapshotResponse.json();
      assert.equal(publishedSnapshot.mode, "sanitized-remote");
      assert.equal(publishedSnapshot.queue.length, 1);
      assert.equal(publishedSnapshot.queue[0].title, "First release");
      assert.doesNotMatch(JSON.stringify(publishedSnapshot), /LOCAL-Q1/);
    } finally {
      await web.close();
    }

    await writeFile(inputPath, JSON.stringify(localSnapshot("Second")), "utf8");
    const second = await runCLI(
      "build",
      "--input",
      inputPath,
      "--output-root",
      outputRoot,
    );
    assert.notEqual(second.releaseId, first.releaseId);
    await runCLI(
      "activate",
      "--output-root",
      outputRoot,
      "--release-id",
      second.releaseId,
    );
    assert.deepEqual(
      await runCLI("status", "--output-root", outputRoot),
      { releaseId: second.releaseId, rollbackAvailable: true },
    );

    const rollback = await runCLI("rollback", "--output-root", outputRoot);
    assert.equal(rollback.releaseId, first.releaseId);
    assert.equal(rollback.replacedReleaseId, second.releaseId);

    const activeSnapshot = JSON.parse(
      await readFile(
        join(outputRoot, "current", "fixtures", "sanitized-remote.snapshot.json"),
        "utf8",
      ),
    );
    assert.equal(activeSnapshot.queue[0].title, "First release");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
