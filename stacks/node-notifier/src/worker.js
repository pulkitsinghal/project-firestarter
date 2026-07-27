import { setTimeout as delay } from "node:timers/promises";

import { Worker } from "bullmq";
import IORedis from "ioredis";

import { redisConnectionOptions } from "./queue.js";

function finalAttempt(job) {
  return job.attemptsMade >= (job.opts.attempts ?? 1);
}

async function publish(publisher, channel, event, logger) {
  try {
    await publisher.publish(channel, JSON.stringify(event));
  } catch (error) {
    logger.error("Could not publish a task update", error.message);
  }
}

export async function runDemoTask(job, { taskDelayMs }) {
  await job.updateProgress({ percent: 10, stage: "started" });
  await delay(taskDelayMs);
  await job.updateProgress({ percent: 100, stage: "finished" });

  return {
    summary: `Finished: ${job.data.message}`,
    completedAt: new Date().toISOString(),
  };
}

export async function createTaskWorker({
  redisUrl,
  redisTls = {},
  queueName,
  eventChannel,
  taskDelayMs = 1200,
  workerConcurrency = 4,
  processor = runDemoTask,
  logger = console,
}) {
  const connection = redisConnectionOptions(redisUrl, redisTls);
  const publisher = new IORedis({
    ...connection,
    lazyConnect: true,
    maxRetriesPerRequest: null,
  });
  publisher.on("error", (error) => {
    logger.error("Notification publisher error", error.message);
  });
  await publisher.connect();
  const pendingPublications = new Set();

  function queuePublication(event) {
    const publication = publish(
      publisher,
      eventChannel,
      event,
      logger,
    ).finally(() => pendingPublications.delete(publication));
    pendingPublications.add(publication);
  }

  const worker = new Worker(
    queueName,
    (job) => processor(job, { taskDelayMs }),
    {
      connection,
      concurrency: workerConcurrency,
    },
  );

  worker.on("active", (job) => {
    queuePublication({
      taskId: String(job.id),
      notificationRoom: job.data.notificationRoom,
      status: "running",
    });
  });

  worker.on("completed", (job, result) => {
    queuePublication({
      taskId: String(job.id),
      notificationRoom: job.data.notificationRoom,
      status: "completed",
      result,
    });
  });

  worker.on("failed", (job) => {
    if (!job || !finalAttempt(job)) {
      return;
    }

    queuePublication({
      taskId: String(job.id),
      notificationRoom: job.data.notificationRoom,
      status: "failed",
      error: "Task failed after all retry attempts.",
    });
  });

  worker.on("error", (error) => {
    logger.error("Task worker error", error.message);
  });

  await worker.waitUntilReady();

  let closed = false;
  return {
    worker,
    async close() {
      if (closed) {
        return;
      }
      closed = true;
      await worker.close();
      await Promise.allSettled(pendingPublications);
      await publisher.quit();
    },
  };
}
