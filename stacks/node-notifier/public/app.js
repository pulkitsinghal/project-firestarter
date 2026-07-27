const STORAGE_KEY = "{{ project_slug }}-task-ids";
const MAX_REMEMBERED_TASKS = 12;

const form = document.querySelector("#task-form");
const messageInput = document.querySelector("#task-message");
const formError = document.querySelector("#form-error");
const taskList = document.querySelector("#task-list");
const emptyState = document.querySelector("#empty-state");
const taskTemplate = document.querySelector("#task-template");
const connectionDot = document.querySelector("#connection-dot");
const connectionStatus = document.querySelector("#connection-status");

const taskElements = new Map();

function rememberedTaskIds() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(value)
      ? value.filter((id) => typeof id === "string").slice(0, MAX_REMEMBERED_TASKS)
      : [];
  } catch {
    return [];
  }
}

function rememberTask(taskId) {
  const ids = [
    taskId,
    ...rememberedTaskIds().filter((existing) => existing !== taskId),
  ].slice(0, MAX_REMEMBERED_TASKS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
}

function forgetTask(taskId) {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(
      rememberedTaskIds().filter((existing) => existing !== taskId),
    ),
  );
}

function statusLabel(status) {
  return {
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
  }[status] ?? "Checking";
}

function renderTask(task) {
  emptyState?.remove();

  let element = taskElements.get(task.taskId);
  if (!element) {
    element = taskTemplate.content.firstElementChild.cloneNode(true);
    taskElements.set(task.taskId, element);
    taskList.prepend(element);
  }

  element.dataset.status = task.status;
  element.querySelector(".task__status").textContent = statusLabel(task.status);
  element.querySelector(".task__message").textContent =
    task.message ?? "Loading task…";
  element.querySelector(".task__id").textContent = task.taskId;

  const timestamp = task.result?.completedAt ?? task.createdAt;
  const time = element.querySelector(".task__time");
  time.dateTime = timestamp ?? "";
  time.textContent = timestamp
    ? new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(timestamp))
    : "";

  const result = element.querySelector(".task__result");
  result.textContent =
    task.result?.summary ??
    task.error ??
    (task.status === "running"
      ? "The worker has claimed this job."
      : "Waiting for a worker.");

  const acknowledgement = element.querySelector(".task__ack");
  const acknowledgedAt = task.delivery?.acknowledgedAt;
  const terminal = task.status === "completed" || task.status === "failed";
  acknowledgement.hidden = !terminal;
  acknowledgement.disabled = Boolean(acknowledgedAt);
  acknowledgement.dataset.taskId = task.taskId;
  acknowledgement.textContent = acknowledgedAt ? "Seen" : "Mark seen";
}

async function fetchTask(taskId) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
    headers: { Accept: "application/json" },
  });

  if (response.status === 404) {
    forgetTask(taskId);
    return;
  }
  if (!response.ok) {
    throw new Error("Could not refresh task state.");
  }
  renderTask(await response.json());
}

async function fetchRecentTasks() {
  const response = await fetch("/api/tasks?limit=12", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error("Could not load recent task state.");
  }
  const body = await response.json();
  for (const task of body.tasks ?? []) {
    rememberTask(task.taskId);
    renderTask(task);
  }
}

async function reconcileTasks() {
  await Promise.allSettled([
    fetchRecentTasks(),
    ...rememberedTaskIds().map(fetchTask),
  ]);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;

  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: messageInput.value }),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error ?? "Could not queue the task.");
    }

    rememberTask(body.taskId);
    renderTask({
      taskId: body.taskId,
      status: body.status,
      message: messageInput.value.trim(),
      createdAt: new Date().toISOString(),
    });
  } catch (error) {
    formError.textContent = error.message;
  } finally {
    button.disabled = false;
    messageInput.focus();
  }
});

taskList.addEventListener("click", async (event) => {
  const button = event.target.closest(".task__ack");
  if (!button || button.disabled) {
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/tasks/${encodeURIComponent(button.dataset.taskId)}/ack`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
      },
    );
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error ?? "Could not acknowledge this task.");
    }
    await fetchTask(button.dataset.taskId);
  } catch (error) {
    formError.textContent = error.message;
    button.disabled = false;
  }
});

const socket = io({
  transports: ["websocket"],
});

socket.on("connect", () => {
  connectionDot.dataset.connected = "true";
  connectionStatus.textContent = "Live notifications connected";
  void reconcileTasks();
});

socket.on("disconnect", () => {
  connectionDot.dataset.connected = "false";
  connectionStatus.textContent = "Disconnected; saved task state is still available";
});

socket.on("connect_error", () => {
  connectionDot.dataset.connected = "false";
  connectionStatus.textContent = "Live connection unavailable; retrying";
});

socket.on("task:update", (event) => {
  if (typeof event?.taskId === "string") {
    void fetchTask(event.taskId);
  }
});

void reconcileTasks();
