import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

import { io as createSocketClient } from "socket.io-client";

import { createNotifierApi } from "../../src/api.js";
import { createTaskWorker } from "../../src/worker.js";

const redisUrl = process.env.TEST_REDIS_URL;
const integrationTest = redisUrl ? test : test.skip;

const logger = {
  error() {},
  warn() {},
};

function testSessionSecret(label) {
  return `${label}-test-fixture-`.repeat(3);
}

function baseUrl(address) {
  return `http://127.0.0.1:${address.port}`;
}

function cookieFrom(response) {
  return response.headers.get("set-cookie").split(";", 1)[0];
}

async function establishSession(url) {
  const response = await fetch(`${url}/api/session`);
  assert.equal(response.status, 204);
  return cookieFrom(response);
}

function waitForSocket(socket, eventName, predicate = () => true) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out waiting for ${eventName}`));
    }, 5000);

    function onEvent(value) {
      if (predicate(value)) {
        cleanup();
        resolve(value);
      }
    }

    function onError(error) {
      cleanup();
      reject(error);
    }

    function cleanup() {
      clearTimeout(timeout);
      socket.off(eventName, onEvent);
      socket.off("connect_error", onError);
    }

    socket.on(eventName, onEvent);
    socket.on("connect_error", onError);
  });
}

async function waitForTask(url, cookie, taskId, predicate) {
  const headers =
    typeof cookie === "string" ? { Cookie: cookie } : cookie;
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const response = await fetch(`${url}/api/tasks/${taskId}`, {
      headers,
    });
    assert.equal(response.status, 200);
    const task = await response.json();
    if (predicate(task)) {
      return task;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("Task did not reach the expected state");
}

async function waitForCompleted(url, cookie, taskId) {
  return waitForTask(
    url,
    cookie,
    taskId,
    (task) => task.status === "completed",
  );
}

function expectNoSocketEvent(
  socket,
  eventName,
  predicate,
  durationMs = 250,
) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      socket.off(eventName, onEvent);
      resolve();
    }, durationMs);
    function onEvent(value) {
      if (predicate(value)) {
        clearTimeout(timeout);
        socket.off(eventName, onEvent);
        reject(new Error(`Unexpected ${eventName}`));
      }
    }
    socket.on(eventName, onEvent);
  });
}

integrationTest(
  "cross-instance notifications are fast and missed events are recoverable",
  async (context) => {
    const suffix = randomUUID().replaceAll("-", "");
    const shared = {
      redisUrl,
      queueName: `notifier-${suffix}`,
      eventChannel: `notifier-${suffix}:events`,
      sessionSecret: testSessionSecret("integration"),
      publicOrigin: null,
      isProduction: false,
      logger,
    };

    const apiOne = await createNotifierApi({ ...shared, port: 0 });
    const apiTwo = await createNotifierApi({ ...shared, port: 0 });
    const worker = await createTaskWorker({
      ...shared,
      taskDelayMs: 40,
      workerConcurrency: 2,
    });
    const firstUrl = baseUrl(await apiOne.start());
    const secondUrl = baseUrl(await apiTwo.start());

    const sessionCookie = await establishSession(firstUrl);
    const socket = createSocketClient(secondUrl, {
      autoConnect: false,
      extraHeaders: {
        Cookie: sessionCookie,
        Origin: secondUrl,
      },
      transports: ["websocket"],
    });

    context.after(async () => {
      socket.disconnect();
      await apiOne.queue.obliterate({ force: true });
      await Promise.all([
        worker.close(),
        apiOne.close(),
        apiTwo.close(),
      ]);
    });

    const connected = waitForSocket(socket, "connect");
    socket.connect();
    await connected;

    const completionEvent = waitForSocket(
      socket,
      "task:update",
      (event) => event.status === "completed",
    );
    const createResponse = await fetch(`${firstUrl}/api/tasks`, {
      method: "POST",
      headers: {
        Cookie: sessionCookie,
        Origin: firstUrl,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "cross-instance task" }),
    });
    assert.equal(createResponse.status, 202);
    const created = await createResponse.json();

    const event = await completionEvent;
    assert.equal(event.taskId, created.taskId);
    assert.equal(event.result.summary, "Finished: cross-instance task");

    const task = await waitForCompleted(
      firstUrl,
      sessionCookie,
      created.taskId,
    );
    assert.equal(task.result.summary, "Finished: cross-instance task");

    const otherSession = await establishSession(firstUrl);
    const unauthorized = await fetch(
      `${firstUrl}/api/tasks/${created.taskId}`,
      { headers: { Cookie: otherSession } },
    );
    assert.equal(unauthorized.status, 404);

    const rejectedOrigin = await fetch(`${firstUrl}/api/tasks`, {
      method: "POST",
      headers: {
        Cookie: sessionCookie,
        Origin: "https://attacker.invalid",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "blocked" }),
    });
    assert.equal(rejectedOrigin.status, 403);

    socket.disconnect();
    const missedResponse = await fetch(`${firstUrl}/api/tasks`, {
      method: "POST",
      headers: {
        Cookie: sessionCookie,
        Origin: firstUrl,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "finish while disconnected" }),
    });
    assert.equal(missedResponse.status, 202);
    const missed = await missedResponse.json();

    const recovered = await waitForCompleted(
      secondUrl,
      sessionCookie,
      missed.taskId,
    );
    assert.equal(recovered.result.summary, "Finished: finish while disconnected");
  },
);

integrationTest(
  "worker failures use the configured exponential retry policy",
  async (context) => {
    const suffix = randomUUID().replaceAll("-", "");
    const shared = {
      redisUrl,
      queueName: `notifier-retry-${suffix}`,
      eventChannel: `notifier-retry-${suffix}:events`,
      sessionSecret: testSessionSecret("retry"),
      publicOrigin: null,
      isProduction: false,
      logger,
    };
    let processorCalls = 0;

    const api = await createNotifierApi({ ...shared, port: 0 });
    const worker = await createTaskWorker({
      ...shared,
      processor: async (job) => {
        processorCalls += 1;
        if (processorCalls < 3) {
          throw new Error("synthetic retryable failure");
        }
        return {
          summary: `Recovered: ${job.data.message}`,
          completedAt: new Date().toISOString(),
        };
      },
      workerConcurrency: 1,
    });
    const url = baseUrl(await api.start());

    context.after(async () => {
      await worker.close();
      await api.queue.obliterate({ force: true });
      await api.close();
    });

    const sessionCookie = await establishSession(url);
    const createResponse = await fetch(`${url}/api/tasks`, {
      method: "POST",
      headers: {
        Cookie: sessionCookie,
        Origin: url,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "retryable task" }),
    });
    assert.equal(createResponse.status, 202);
    const created = await createResponse.json();

    const task = await waitForTask(
      url,
      sessionCookie,
      created.taskId,
      (value) =>
        value.status === "completed" &&
        value.attemptsMade === 3,
    );
    assert.equal(processorCalls, 3);
    assert.equal(task.attemptsMade, 3);
    assert.equal(task.result.summary, "Recovered: retryable task");
  },
);

integrationTest(
  "OIDC identity replays unacknowledged work across devices and enforces limits",
  async (context) => {
    const suffix = randomUUID().replaceAll("-", "");
    const tokenVerifier = async (token) => {
      if (token === "invalid-token") {
        throw new Error("invalid");
      }
      const exp = Math.floor(Date.now() / 1000) + 300;
      if (token === "expiring-token") {
        return {
          payload: {
            sub: "user-1",
            tenant_id: "tenant-a",
            exp: Math.floor(Date.now() / 1000) + 1,
          },
        };
      }
      const identities = {
        "first-token": { sub: "user-1", tenant_id: "tenant-a", exp },
        "refreshed-token": { sub: "user-1", tenant_id: "tenant-a", exp },
        "other-user": { sub: "user-2", tenant_id: "tenant-a", exp },
        "other-tenant": { sub: "user-1", tenant_id: "tenant-b", exp },
      };
      return { payload: identities[token] };
    };
    const shared = {
      redisUrl,
      queueName: `notifier-oidc-${suffix}`,
      eventChannel: `notifier-oidc-${suffix}:events`,
      sessionSecret: testSessionSecret("oidc"),
      publicOrigin: null,
      isProduction: false,
      authMode: "oidc",
      oidcTenantClaim: "tenant_id",
      tokenVerifier,
      taskRateLimit: 2,
      taskRateWindowSeconds: 60,
      taskRetentionSeconds: 600,
      logger,
    };
    const api = await createNotifierApi({ ...shared, port: 0 });
    const worker = await createTaskWorker({
      ...shared,
      taskDelayMs: 30,
      workerConcurrency: 1,
    });
    const url = baseUrl(await api.start());
    const authorization = {
      Authorization: "Bearer first-token",
    };
    const refreshedAuthorization = {
      Authorization: "Bearer refreshed-token",
    };
    const sockets = [];

    context.after(async () => {
      for (const socket of sockets) {
        socket.disconnect();
      }
      await api.queue.obliterate({ force: true });
      await Promise.all([worker.close(), api.close()]);
    });

    const createResponse = await fetch(`${url}/api/tasks`, {
      method: "POST",
      headers: {
        ...authorization,
        Origin: url,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "cross-device task" }),
    });
    assert.equal(createResponse.status, 202);
    const created = await createResponse.json();
    const completed = await waitForCompleted(
      url,
      authorization,
      created.taskId,
    );
    assert.equal(completed.delivery.acknowledgedAt, null);

    const reconnected = createSocketClient(url, {
      autoConnect: false,
      auth: { token: "refreshed-token" },
      extraHeaders: { Origin: url },
      transports: ["websocket"],
    });
    sockets.push(reconnected);
    const replayed = waitForSocket(
      reconnected,
      "task:update",
      (event) => event.taskId === created.taskId && event.replayed === true,
    );
    reconnected.connect();
    await replayed;

    const acknowledgementResponse = await fetch(
      `${url}/api/tasks/${created.taskId}/ack`,
      {
        method: "POST",
        headers: {
          ...refreshedAuthorization,
          Origin: url,
        },
      },
    );
    assert.equal(acknowledgementResponse.status, 200);
    const acknowledgement = await acknowledgementResponse.json();
    assert.match(
      acknowledgement.delivery.acknowledgedAt,
      /^\d{4}-\d{2}-\d{2}T/,
    );
    const repeatedAcknowledgement = await fetch(
      `${url}/api/tasks/${created.taskId}/ack`,
      {
        method: "POST",
        headers: {
          ...refreshedAuthorization,
          Origin: url,
        },
      },
    );
    assert.equal(repeatedAcknowledgement.status, 200);
    assert.equal(
      (await repeatedAcknowledgement.json()).delivery.acknowledgedAt,
      acknowledgement.delivery.acknowledgedAt,
    );

    for (const token of ["other-user", "other-tenant"]) {
      const forbidden = await fetch(`${url}/api/tasks/${created.taskId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      assert.equal(forbidden.status, 404);
    }

    const recentResponse = await fetch(`${url}/api/tasks`, {
      headers: refreshedAuthorization,
    });
    assert.equal(recentResponse.status, 200);
    const recent = await recentResponse.json();
    assert.equal(recent.tasks[0].taskId, created.taskId);
    assert.equal(
      recent.tasks[0].delivery.acknowledgedAt,
      acknowledgement.delivery.acknowledgedAt,
    );

    const secondResponse = await fetch(`${url}/api/tasks`, {
      method: "POST",
      headers: {
        ...refreshedAuthorization,
        Origin: url,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "within limit" }),
    });
    assert.equal(secondResponse.status, 202);
    const limitedResponse = await fetch(`${url}/api/tasks`, {
      method: "POST",
      headers: {
        ...authorization,
        Origin: url,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: "over limit" }),
    });
    assert.equal(limitedResponse.status, 429);
    assert.equal(limitedResponse.headers.get("x-ratelimit-remaining"), "0");
    assert.ok(Number(limitedResponse.headers.get("retry-after")) >= 1);

    reconnected.disconnect();
    const afterAck = createSocketClient(url, {
      autoConnect: false,
      auth: { token: "refreshed-token" },
      extraHeaders: { Origin: url },
      transports: ["websocket"],
    });
    sockets.push(afterAck);
    const ready = waitForSocket(afterAck, "notifier:ready");
    const noAcknowledgedReplay = expectNoSocketEvent(
      afterAck,
      "task:update",
      (event) => event.taskId === created.taskId,
    );
    afterAck.connect();
    await ready;
    await noAcknowledgedReplay;

    const unauthenticated = await fetch(`${url}/api/tasks`);
    assert.equal(unauthenticated.status, 401);
    assert.equal(
      unauthenticated.headers.get("www-authenticate"),
      "Bearer",
    );

    const expiring = createSocketClient(url, {
      autoConnect: false,
      auth: { token: "expiring-token" },
      extraHeaders: { Origin: url },
      transports: ["websocket"],
    });
    sockets.push(expiring);
    const expiringConnected = waitForSocket(expiring, "connect");
    const expiredDisconnect = waitForSocket(
      expiring,
      "disconnect",
      (reason) => reason === "io server disconnect",
    );
    expiring.connect();
    await expiringConnected;
    await expiredDisconnect;
  },
);
