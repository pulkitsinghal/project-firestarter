import assert from "node:assert/strict";
import test from "node:test";

import {
  isTerminalTask,
  parseTaskMessage,
  publicTaskEvent,
} from "../../src/task.js";

test("task messages are trimmed and bounded", () => {
  assert.equal(
    parseTaskMessage({ message: "  prepare report  " }),
    "prepare report",
  );
  assert.throws(() => parseTaskMessage({ message: " " }), /between 1 and 120/);
  assert.throws(
    () => parseTaskMessage({ message: "x".repeat(121) }),
    /between 1 and 120/,
  );
});

test("public task events remove the internal notification room", () => {
  const event = publicTaskEvent({
    taskId: "task-id",
    notificationRoom: "session:private",
    status: "completed",
    result: { summary: "done" },
  });

  assert.deepEqual(event, {
    taskId: "task-id",
    status: "completed",
    result: { summary: "done" },
    error: null,
  });
  assert.equal("notificationRoom" in event, false);
});

test("invalid task events are ignored", () => {
  assert.equal(
    publicTaskEvent({
      taskId: "task-id",
      notificationRoom: "session:private",
      status: "unknown",
    }),
    null,
  );
});

test("only completed and failed tasks are terminal acknowledgements", () => {
  assert.equal(isTerminalTask("completed"), true);
  assert.equal(isTerminalTask("failed"), true);
  assert.equal(isTerminalTask("running"), false);
  assert.equal(isTerminalTask("queued"), false);
});
