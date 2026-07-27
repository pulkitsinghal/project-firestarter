import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { Queue } from "bullmq";
import express from "express";
import helmet from "helmet";
import IORedis from "ioredis";
import { Server as SocketServer } from "socket.io";

import { createIdentityService } from "./identity.js";
import { consumeRateLimit } from "./rate-limit.js";
import {
  jobOptions,
  redisConnectionOptions,
} from "./queue.js";
import { TaskStore } from "./task-store.js";
import {
  isTerminalTask,
  parseTaskMessage,
  presentJob,
  publicTaskEvent,
} from "./task.js";

const publicDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../public",
);

const TASK_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function expectedOrigin(request, configuredOrigin) {
  if (configuredOrigin) {
    return configuredOrigin;
  }

  const host = request.headers.host;
  if (!host) {
    return null;
  }
  const protocol = request.socket.encrypted ? "https" : "http";
  return `${protocol}://${host}`;
}

function originIsAllowed(request, configuredOrigin) {
  const origin = request.headers.origin;
  return Boolean(origin && origin === expectedOrigin(request, configuredOrigin));
}

function requireSameOrigin(configuredOrigin) {
  return (request, response, next) => {
    if (!originIsAllowed(request, configuredOrigin)) {
      response.status(403).json({ error: "Request origin is not allowed." });
      return;
    }
    next();
  };
}

function closeHttpServer(server) {
  if (!server.listening) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

function parseListLimit(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  if (!/^\d+$/.test(value)) {
    const error = new Error("limit must be an integer between 1 and 100");
    error.statusCode = 400;
    throw error;
  }
  const limit = Number(value);
  if (limit < 1 || limit > 100) {
    const error = new Error("limit must be an integer between 1 and 100");
    error.statusCode = 400;
    throw error;
  }
  return limit;
}

function notFound(response) {
  response.status(404).json({ error: "Task not found." });
}

function disconnectAtTokenExpiry(socket, expiresAt) {
  if (!expiresAt) {
    return;
  }
  let timer;
  const schedule = () => {
    const remaining = expiresAt * 1000 - Date.now();
    if (remaining <= 0) {
      socket.disconnect(true);
      return;
    }
    timer = setTimeout(schedule, Math.min(remaining, 2_147_000_000));
  };
  schedule();
  socket.once("disconnect", () => clearTimeout(timer));
}

export async function createNotifierApi({
  redisUrl,
  redisTls = {},
  queueName,
  eventChannel,
  sessionSecret,
  publicOrigin,
  host = "127.0.0.1",
  port = 3000,
  isProduction = false,
  authMode = "anonymous",
  oidcIssuer = null,
  oidcAudience = null,
  oidcJwksUrl = null,
  oidcAlgorithms = ["RS256"],
  oidcTenantClaim = "tenant_id",
  tokenVerifier = null,
  taskRetentionSeconds = 24 * 60 * 60,
  taskRateLimit = 30,
  taskRateWindowSeconds = 60,
  replayLimit = 50,
  logger = console,
}) {
  const connection = redisConnectionOptions(redisUrl, redisTls);
  const queue = new Queue(queueName, {
    connection,
    defaultJobOptions: jobOptions(taskRetentionSeconds),
  });
  const subscriber = new IORedis({
    ...connection,
    lazyConnect: true,
    maxRetriesPerRequest: null,
  });
  const controlRedis = new IORedis({
    ...connection,
    lazyConnect: true,
    maxRetriesPerRequest: 1,
  });

  subscriber.on("error", (error) => {
    logger.error("Notification subscriber error", error.message);
  });
  controlRedis.on("error", () => {
    // Readiness reports failures without logging connection details.
  });

  await Promise.all([
    queue.waitUntilReady(),
    subscriber.connect(),
    controlRedis.connect(),
  ]);

  const taskStore = new TaskStore(controlRedis, {
    namespace: queueName,
    retentionSeconds: taskRetentionSeconds,
  });
  const identities = createIdentityService({
    authMode,
    sessionSecret,
    taskRetentionSeconds,
    secureCookies: isProduction,
    oidcIssuer,
    oidcAudience,
    oidcJwksUrl,
    oidcAlgorithms,
    oidcTenantClaim,
    tokenVerifier,
  });

  const app = express();
  const httpServer = createServer(app);
  const io = new SocketServer(httpServer, {
    allowRequest: (request, callback) => {
      const allowed = originIsAllowed(request, publicOrigin);
      callback(allowed ? null : "origin is not allowed", allowed);
    },
    serveClient: !isProduction,
    transports: ["websocket"],
  });

  async function ownedJob(taskId, ownerKey) {
    if (!TASK_ID_PATTERN.test(taskId)) {
      return null;
    }
    const job = await queue.getJob(taskId);
    return job?.data.ownerKey === ownerKey ? job : null;
  }

  async function taskRepresentation(job) {
    return presentJob(
      job,
      await taskStore.acknowledgement(String(job.id)),
    );
  }

  async function recentTasks(ownerKey, limit) {
    const taskIds = await taskStore.listTaskIds(ownerKey, limit);
    const jobs = await Promise.all(
      taskIds.map((taskId) => queue.getJob(taskId)),
    );
    const ownedJobs = jobs.filter(
      (job) => job?.data.ownerKey === ownerKey,
    );
    return Promise.all(ownedJobs.map(taskRepresentation));
  }

  io.use(async (socket, next) => {
    try {
      socket.data.identity = await identities.authenticateSocket(socket);
      next();
    } catch {
      next(new Error("authentication is required"));
    }
  });

  io.on("connection", (socket) => {
    const {
      notificationRoom,
      ownerKey,
      expiresAt,
    } = socket.data.identity;
    disconnectAtTokenExpiry(socket, expiresAt);
    socket.join(notificationRoom);
    socket.emit("notifier:ready", {
      connectedAt: new Date().toISOString(),
    });

    void recentTasks(ownerKey, replayLimit)
      .then((tasks) => {
        for (const task of tasks) {
          if (
            isTerminalTask(task.status) &&
            !task.delivery.acknowledgedAt
          ) {
            socket.emit("task:update", {
              taskId: task.taskId,
              status: task.status,
              result: task.result,
              error: task.error,
              replayed: true,
            });
          }
        }
      })
      .catch((error) => {
        logger.warn("Could not replay pending task updates", error.message);
      });
  });

  subscriber.on("message", (channel, payload) => {
    if (channel !== eventChannel) {
      return;
    }

    try {
      const event = JSON.parse(payload);
      const publicEvent = publicTaskEvent(event);
      if (publicEvent) {
        io.to(event.notificationRoom).emit("task:update", publicEvent);
      }
    } catch {
      logger.warn("Ignored an invalid notification event");
    }
  });
  await subscriber.subscribe(eventChannel);

  app.disable("x-powered-by");
  app.use(
    helmet({
      contentSecurityPolicy: {
        directives: {
          "default-src": ["'self'"],
          "base-uri": ["'none'"],
          "connect-src": ["'self'"],
          "font-src": ["'self'"],
          "form-action": ["'self'"],
          "frame-ancestors": ["'none'"],
          "img-src": ["'self'", "data:"],
          "object-src": ["'none'"],
          "script-src": ["'self'"],
          "style-src": ["'self'"],
          // Helmet enables this directive by default. Disable it only for the
          // local HTTP tutorial: internal Compose hostnames such as `api` are
          // not covered by browsers' localhost exception, so upgrading their
          // CSS/JS requests to HTTPS produces a deceptively unstyled, inert UI.
          "upgrade-insecure-requests": isProduction ? [] : null,
        },
      },
    }),
  );

  app.get("/health/live", (_request, response) => {
    response.json({ status: "ok" });
  });

  app.get("/health/ready", async (_request, response) => {
    try {
      await controlRedis.ping();
      response.json({ status: "ready" });
    } catch {
      response.status(503).json({ status: "not-ready" });
    }
  });

  app.use(express.json({ limit: "8kb", strict: true }));
  app.use(async (request, response, next) => {
    try {
      request.identity = await identities.authenticateRequest(
        request,
        response,
      );
      next();
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/session", (_request, response) => {
    response.setHeader("Cache-Control", "no-store");
    response.status(204).end();
  });

  app.post(
    "/api/tasks",
    requireSameOrigin(publicOrigin),
    async (request, response, next) => {
      try {
        const rate = await consumeRateLimit(controlRedis, {
          namespace: queueName,
          ownerKey: request.identity.ownerKey,
          limit: taskRateLimit,
          windowSeconds: taskRateWindowSeconds,
        });
        response.setHeader("X-RateLimit-Limit", String(rate.limit));
        response.setHeader(
          "X-RateLimit-Remaining",
          String(rate.remaining),
        );
        response.setHeader("X-RateLimit-Reset", String(rate.resetAt));
        if (!rate.allowed) {
          response.setHeader(
            "Retry-After",
            String(Math.max(1, rate.resetAt - Math.floor(Date.now() / 1000))),
          );
          response.status(429).json({
            error: "Too many task requests. Try again after the rate limit resets.",
          });
          return;
        }

        const message = parseTaskMessage(request.body);
        const taskId = randomUUID();
        await taskStore.remember(request.identity.ownerKey, taskId);
        try {
          await queue.add(
            "demo-task",
            {
              message,
              ownerKey: request.identity.ownerKey,
              notificationRoom: request.identity.notificationRoom,
              requestedAt: new Date().toISOString(),
            },
            { jobId: taskId },
          );
        } catch (error) {
          await taskStore
            .forget(request.identity.ownerKey, taskId)
            .catch(() => {});
          throw error;
        }

        response
          .status(202)
          .location(`/api/tasks/${taskId}`)
          .json({ taskId, status: "queued" });
      } catch (error) {
        next(error);
      }
    },
  );

  app.get("/api/tasks", async (request, response, next) => {
    try {
      const limit = parseListLimit(request.query.limit, replayLimit);
      response.setHeader("Cache-Control", "no-store");
      response.json({
        tasks: await recentTasks(request.identity.ownerKey, limit),
      });
    } catch (error) {
      next(error);
    }
  });

  app.get("/api/tasks/:taskId", async (request, response, next) => {
    try {
      const job = await ownedJob(
        request.params.taskId,
        request.identity.ownerKey,
      );
      if (!job) {
        notFound(response);
        return;
      }

      response.setHeader("Cache-Control", "no-store");
      response.json(await taskRepresentation(job));
    } catch (error) {
      next(error);
    }
  });

  app.post(
    "/api/tasks/:taskId/ack",
    requireSameOrigin(publicOrigin),
    async (request, response, next) => {
      try {
        const job = await ownedJob(
          request.params.taskId,
          request.identity.ownerKey,
        );
        if (!job) {
          notFound(response);
          return;
        }

        const task = await taskRepresentation(job);
        if (!isTerminalTask(task.status)) {
          response.status(409).json({
            error: "Only completed or failed tasks can be acknowledged.",
          });
          return;
        }

        response.setHeader("Cache-Control", "no-store");
        response.json({
          taskId: String(job.id),
          delivery: await taskStore.acknowledge(String(job.id)),
        });
      } catch (error) {
        next(error);
      }
    },
  );

  if (!isProduction) {
    app.use(
      express.static(publicDirectory, {
        etag: true,
        maxAge: 0,
      }),
    );
  }

  app.use("/api", (_request, response) => {
    response.status(404).json({ error: "API route not found." });
  });

  app.use((error, _request, response, _next) => {
    const statusCode =
      Number.isInteger(error.statusCode) &&
      error.statusCode >= 400 &&
      error.statusCode < 500
        ? error.statusCode
        : error.type === "entity.too.large"
          ? 413
          : 500;

    if (error.authenticate) {
      response.setHeader("WWW-Authenticate", error.authenticate);
    }
    if (statusCode >= 500) {
      logger.error("Request failed", error.message);
    }
    response.status(statusCode).json({
      error:
        statusCode === 500
          ? "Unexpected server error."
          : error.message,
    });
  });

  let closed = false;

  return {
    app,
    httpServer,
    io,
    queue,
    async start() {
      return new Promise((resolve, reject) => {
        const onError = (error) => {
          httpServer.off("listening", onListening);
          reject(error);
        };
        const onListening = () => {
          httpServer.off("error", onError);
          resolve(httpServer.address());
        };
        httpServer.once("error", onError);
        httpServer.once("listening", onListening);
        httpServer.listen(port, host);
      });
    },
    async close() {
      if (closed) {
        return;
      }
      closed = true;

      await new Promise((resolve) => io.close(resolve));
      await closeHttpServer(httpServer);
      await Promise.allSettled([
        queue.close(),
        subscriber.quit(),
        controlRedis.quit(),
      ]);
    },
  };
}
