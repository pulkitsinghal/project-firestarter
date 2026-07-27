import { loadConfig } from "./config.js";
import { createTaskWorker } from "./worker.js";

const config = loadConfig();
const taskWorker = await createTaskWorker(config);

console.log(
  `Task worker is ready with concurrency ${config.workerConcurrency}`,
);

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  console.log(`Received ${signal}; shutting down`);
  await taskWorker.close();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    void shutdown(signal).then(() => process.exit(0));
  });
}
