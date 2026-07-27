import { createNotifierApi } from "./api.js";
import { loadConfig } from "./config.js";

const config = loadConfig();
const api = await createNotifierApi(config);
await api.start();

console.log(`Notifier tutorial listening at ${config.publicOrigin}`);

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  console.log(`Received ${signal}; shutting down`);
  await api.close();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    void shutdown(signal).then(() => process.exit(0));
  });
}
