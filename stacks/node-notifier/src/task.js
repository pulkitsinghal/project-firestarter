const TASK_STATES = new Map([
  ["active", "running"],
  ["completed", "completed"],
  ["failed", "failed"],
  ["delayed", "queued"],
  ["paused", "queued"],
  ["prioritized", "queued"],
  ["waiting", "queued"],
  ["waiting-children", "queued"],
]);

export function parseTaskMessage(body) {
  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message || message.length > 120) {
    const error = new Error("message must contain between 1 and 120 characters");
    error.statusCode = 400;
    throw error;
  }
  return message;
}

export function isTerminalTask(status) {
  return status === "completed" || status === "failed";
}

export async function presentJob(job, acknowledgement = null) {
  const rawState = await job.getState();
  const status = TASK_STATES.get(rawState) ?? "queued";

  return {
    taskId: String(job.id),
    status,
    message: job.data.message,
    progress: job.progress,
    attemptsMade: job.attemptsMade,
    createdAt: new Date(job.timestamp).toISOString(),
    result: status === "completed" ? job.returnvalue : null,
    error: status === "failed" ? "Task failed after all retry attempts." : null,
    delivery: {
      acknowledgedAt: acknowledgement?.acknowledgedAt ?? null,
    },
  };
}

export function publicTaskEvent(event) {
  if (
    !event ||
    typeof event.taskId !== "string" ||
    typeof event.notificationRoom !== "string" ||
    !["running", "completed", "failed"].includes(event.status)
  ) {
    return null;
  }

  return {
    taskId: event.taskId,
    status: event.status,
    result: event.result ?? null,
    error: event.error ?? null,
  };
}
