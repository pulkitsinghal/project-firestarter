# Guided notifier tutorial

## Learning objectives

By the end of this lab, you should be able to explain:

1. why an API returns `202 Accepted` before background work is complete;
2. which data must be durable and which event may be ephemeral;
3. why a socket ID is not authentication;
4. how a disconnected browser recovers missed state; and
5. what an explicit delivery acknowledgement proves; and
6. what changes when API and worker processes scale independently.

The exercises run locally. They do not create cloud resources or use a paid
service.

## 1. Start from a clean clone

```sh
make up
```

Wait for the API health check, then open <http://localhost:{{ port_web }}>.

You should see three services:

- `api` serves the page, validates task requests, owns Socket.IO connections,
  and reads job state;
- `worker` claims queued jobs and produces results; and
- `redis` stores BullMQ state and fans out live update hints.

In another terminal, follow the application logs:

```sh
docker compose logs -f api worker
```

No Redis port is published to your host. Only the demo page is reachable at
`127.0.0.1:{{ port_web }}`.

If port {{ port_web }} is already occupied, keep the container port unchanged and choose
another loopback port and matching public origin:

```sh
HOST_PORT=3011 PUBLIC_ORIGIN=http://localhost:3011 make up
```

**Checkpoint:** `curl http://localhost:{{ port_web }}/health/ready` should
return `{"status":"ready"}`. A live page without a ready dependency is not a
healthy stack.

## 2. Trace the normal path

Enter a short message and choose **Run task**.

Observe:

1. The browser receives a task ID and shows `Queued` immediately.
2. A separate worker claims the job.
3. The worker saves the result before publishing a live update hint.
4. The API instance with your socket emits `task:update`.
5. The browser reads the task endpoint and renders the saved result.
6. **Mark seen** stores an idempotent acknowledgement outside the socket.

The browser never receives or submits its Socket.IO connection ID. Open
Developer Tools and inspect the `POST /api/tasks` response: it contains a task
ID, not a socket target.

The API accepts only same-origin JSON writes. The session cookie is HttpOnly,
so the page's JavaScript cannot read it.

## 3. Prove the queue survives a worker outage

Stop only the worker:

```sh
docker compose stop worker
```

Queue a task in the browser. It remains `Queued` because Redis holds it. Start
the worker again:

```sh
docker compose start worker
```

The worker claims the existing job and the browser receives the result. This
is the key difference between a durable work queue and the original
`PUBLISH`/`SUBSCRIBE` task path.

## 4. Prove a socket event is not the source of truth

Use a longer simulated task:

```sh
make down
TASK_DELAY_MS=8000 make up
```

Queue a task, then close the tab before it finishes. Wait eight seconds and
reopen <http://localhost:{{ port_web }}>.

The original demo could not notify a new socket ID. This page keeps the
anonymous identity in a signed cookie, indexes recent tasks by a server-derived
owner key, and reads them from the API after load. Local storage remains a
client-side fallback. The saved result appears even though the live socket
event was missed.

Do not choose **Mark seen**, close the tab, and open it again. The API replays
the unacknowledged terminal task to the replacement socket. Now choose
**Mark seen**. Repeating the acknowledgement returns the original timestamp,
and later reconnects no longer replay that task.

This local exercise proves recovery for one anonymous browser identity.
Production mode applies the same mechanism to a validated tenant and subject
across devices.

## 5. Exercise cross-instance fan-out

Run the integration suite:

```sh
make test
```

The test:

1. creates two API instances against one isolated queue;
2. establishes a signed session through API A;
3. connects a Socket.IO client to API B;
4. submits the task to API A;
5. receives the worker's completion through API B;
6. proves another session cannot read the task; and
7. disconnects the socket and recovers a later result through the task API.

A second integration case runs the production identity contract without a
vendor dependency. It proves token refresh and cross-device replay for the
same tenant and subject, isolation across users and tenants, idempotent
acknowledgement, suppression after acknowledgement, and Redis-backed `429`
rate limiting.

That is a bounded functional proof of the stack's scale-out design. It is not
a load, chaos, or production failover test.

## 6. Read the retry policy

`src/queue.js` gives each job three attempts with exponential backoff. In
BullMQ, a worker exception moves the job through the retry policy; the final
failure is retained for inspection and emitted as a generic browser update.

The starter processor only waits and returns a string, so the interactive path
does not intentionally fail. In a real processor:

- throw an `Error` for a retryable failure;
- make the operation idempotent or use an idempotency key;
- classify permanent failures so they are not retried blindly;
- cap concurrency against downstream capacity; and
- alert on exhausted retries and stalled jobs.

Queue retry and browser redelivery are different problems. Queue retry reruns
work. Browser recovery reads the already-saved outcome.

## 7. Inspect the security boundary

The local demo provides:

- a random HMAC-signed session cookie;
- HttpOnly and SameSite=Strict cookie attributes;
- exact-Origin checks for task creation;
- server-derived, non-public Socket.IO rooms;
- task ownership checks that return 404 across sessions;
- bounded JSON and message length;
- Helmet headers and a restrictive Content Security Policy;
- an unprivileged, read-only application container; and
- no host-published data-store port.

Production mode adds:

- JWT signature, algorithm, issuer, audience, expiration, subject, and tenant
  validation against a fixed JWKS URL;
- stable cross-device owner and room derivation without storing raw claims;
- token-expiry disconnect for sockets;
- Redis-backed per-identity task rate limiting;
- recent-task indexing and explicit acknowledgement;
- configurable bounded retention; and
- startup enforcement for HTTPS origin and ACL-authenticated TLS Redis.

The application still delegates login, consent, MFA, token issuance and
revocation, tenant membership, and authorization policy to the chosen identity
provider. It does not terminate TLS, create secrets, deploy Redis, configure
backups, or choose compliance retention.

## 8. Follow the production contract

Read [the production guide](production.md). It shows the required environment,
client authorization headers and Socket.IO handshake, Redis ACL/TLS boundary,
acknowledgement semantics, and pre-deployment checklist.

Do not copy the local Compose secret or anonymous identity into production.
Production startup rejects that configuration.

## 9. Clean up

Stop containers while preserving recent Redis state:

```sh
make down
```

If you intentionally want to delete the tutorial's named data volume too:

```sh
make clean-data
```

The second command permanently removes queued jobs and saved demo results.

## 10. Replace the simulated operation safely

The tutorial is complete when you can explain it; a product integration starts
only after that. Replace the body of `createTaskProcessor` in `src/task.js`
with one bounded, idempotent operation and keep the transport contract stable:

1. validate and normalize the request before queueing;
2. store only the identifiers and minimum input the worker needs;
3. make retries safe with an idempotency key or an atomic downstream write;
4. return a user-safe result and log internal diagnostics separately;
5. add a unit test for permanent failure and an integration test for retry;
6. regenerate `docs/STORYBOARD.md` with `make storyboard`; and
7. record the acceptance, failure, cleanup, and rollback evidence in
   `docs/FEATURE_HANDOFF.md`.

Do not connect the starter to a production identity provider, queue, or paid
service merely to finish the tutorial. Those are explicit deployment gates.
