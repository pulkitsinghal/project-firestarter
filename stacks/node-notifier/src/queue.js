import { readFileSync } from "node:fs";

export function jobOptions(retentionSeconds = 24 * 60 * 60) {
  return {
    attempts: 3,
    backoff: {
      type: "exponential",
      delay: 500,
    },
    removeOnComplete: {
      age: retentionSeconds,
      count: 1000,
    },
    removeOnFail: {
      age: retentionSeconds,
      count: 1000,
    },
  };
}

export function redisConnectionOptions(
  redisUrl,
  {
    caFile = null,
    certFile = null,
    keyFile = null,
  } = {},
  readFile = readFileSync,
) {
  const url = new URL(redisUrl);
  const options = {
    host: url.hostname,
    port: Number(url.port || 6379),
    maxRetriesPerRequest: null,
  };

  if (url.username) {
    options.username = decodeURIComponent(url.username);
  }
  if (url.password) {
    options.password = decodeURIComponent(url.password);
  }
  if (url.pathname && url.pathname !== "/") {
    options.db = Number(url.pathname.slice(1));
  }
  if (url.protocol === "rediss:") {
    options.tls = {
      servername: url.hostname,
    };
    if (caFile) {
      options.tls.ca = readFile(caFile);
    }
    if (certFile && keyFile) {
      options.tls.cert = readFile(certFile);
      options.tls.key = readFile(keyFile);
    }
  }

  return options;
}
