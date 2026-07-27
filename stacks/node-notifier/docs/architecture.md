# Architecture and modernization notes

## Teaching intent worth preserving

The 2016 repository compressed an important distributed-systems lesson into a
small diagram and four visible roles: browser, web server, queue, worker, and
notifier. Its README also admitted two non-obvious limitations:

- a notifier instance owns only its local socket connections, so naive
  horizontal scaling misroutes results; and
- refreshing a browser changes the socket ID, so a result addressed only to
  that connection cannot be recovered.

The `develop` branch added a useful direct-notification curl example and image
publishing notes. Issue #1 then articulated the missing requirement precisely:
store undelivered notifications and associate them with stable user identity
rather than a transient socket.

Those are useful prompts for a tutorial. The replacement makes the answer
executable instead of leaving it as a proposed second diagram.

## Verified limitations in the default branch

### The documented clean-clone command could not install the application

The README instructed readers to run `docker-compose ... up --build`, but each
Node 4 Dockerfile only set a work directory and entrypoint. It did not copy
`package.json` or run `npm install`. Compose bind-mounted source directories,
which likewise contained no `node_modules` in a clean clone.

All three `package.json` files defined `npm test` as an intentional failure.
There was no lockfile on the default branch and no CI workflow.

### Work and notifications were both lossy

The web server used Redis `PUBLISH` as its task queue. Redis documents Pub/Sub
as at-most-once: a worker that is disconnected when a message is published
cannot recover it.

The worker then made a fire-and-forget HTTP request to `/notify` and did not
inspect an error or response. The notifier returned 500 when the socket had
gone away, but nothing persisted or retried that result. Refreshing the tab
therefore lost the only delivery target.

### A transport identifier was treated as authorization

The README explicitly claimed that the random, short-lived socket ID removed
the need for notifier authentication. In the code:

- the socket ID was sent to the browser, web server, queue, worker, and
  notifier;
- `/notify` was unauthenticated and published on host port 3001;
- any caller with a current ID could inject a notification;
- connection IDs and request bodies were logged; and
- Redis was published on host port 6379 without authentication.

A Socket.IO ID identifies one connection. It is public transport metadata, not
a user identity, secret, authorization decision, or delivery receipt.

### The dependency and container assumptions expired

- Node 4 reached end of life in 2018.
- The services pinned 2016 releases of Express, Socket.IO, the Redis client,
  `request`, and Redis 2.8.
- The legacy top-level Compose `version: "2"` is now only backward-compatible
  metadata; the Compose Specification is current.
- Images ran with broad defaults and had no health checks, graceful shutdown,
  dependency audit, request bounds, origin policy, or security headers.
- The browser hard-coded `localhost:3001`, which only works when the browser
  and container host are the same machine.

## Replacement decisions

### Durable work, ephemeral wake-up

BullMQ stores the job and result in Redis, retries processor failures three
times with exponential backoff, and retains recent terminal state. Redis
Pub/Sub carries only `task:update`, a low-latency wake-up to API replicas.

This distinction is deliberate. Both Redis Pub/Sub and Socket.IO document
at-most-once delivery gaps. The browser therefore treats every socket event as
a reason to read `GET /api/tasks/:taskId`, and it repeats that read on reconnect
or page load.

### Two explicit identity modes

Local tutorial mode creates a random session identifier, signs it with
HMAC-SHA-256, and stores it in an HttpOnly, SameSite=Strict cookie.

Production mode accepts JWT access tokens from an external identity provider.
It pins an asymmetric algorithm allowlist and validates the signature, issuer,
audience, expiration, subject, and configured tenant claim against a fixed
JWKS URL. The raw claims are not stored in task data. HMAC-derived owner and
room keys bind the validated `(tenant, subject)` pair to tasks and sockets.
The socket is disconnected when its validated token expires.

In both modes the browser cannot select a room, a guessed task ID does not
grant access, and the internal room is removed from public events. Production
devices with refreshed tokens for the same tenant and subject resolve to the
same owner, while a different tenant or subject receives a non-enumerating
404.

### Redelivery, acknowledgement, and bounded retention

Each owner has a Redis sorted-set index of recent task IDs. A reconnect reads
that index and replays terminal tasks without an acknowledgement. The
authoritative `GET /api/tasks` and `GET /api/tasks/:id` responses still carry
the task state, so the replay event remains only a wake-up.

`POST /api/tasks/:id/ack` records the first acknowledgement timestamp with
Redis `SET NX`. Repeating the request returns the same receipt, making the
operation idempotent. This proves application receipt by an authenticated
client; it does not prove a human read or acted on the result.

Job state, owner indexes, and acknowledgements share
`TASK_RETENTION_SECONDS` (24 hours by default, 5 minutes to 30 days allowed).
Task creation uses a Redis-backed fixed-window limit scoped to the derived
owner key. The default is 30 tasks per 60 seconds.

### Horizontal event fan-out

Every API replica subscribes to the completion channel. When a worker
publishes one event, Redis sends it to every active replica; only the replica
with a local socket in the derived room emits to that browser. The client uses
WebSocket-only transport, so Socket.IO does not require sticky sessions for
its multi-request long-polling transport.

The integration test proves the repository-specific behavior with two API
instances. A production deployment still needs a load balancer, resource
limits, readiness routing, and operational evidence at its intended scale.

### Reduced local exposure

Compose publishes only the API on `127.0.0.1`. Redis is reachable only on the
Compose network. Application containers run as the unprivileged `node` user
with a read-only filesystem, dropped capabilities, and
`no-new-privileges`.

The UI is same-origin, uses external scripts/styles compatible with a strict
Content Security Policy, and inserts all task text with `textContent`.
State-changing API requests require the configured exact Origin and bounded
JSON input.

Production configuration additionally fails closed unless:

- `AUTH_MODE=oidc`;
- `PUBLIC_ORIGIN` uses HTTPS;
- the issuer and JWKS URLs use HTTPS;
- an explicit JWT audience and tenant claim are configured; and
- Redis uses `rediss://` with an ACL username and password.

Private Redis certificate authorities and mutual-TLS client certificates can
be mounted read-only and supplied by file path. The application never logs
connection URLs, credentials, access tokens, certificate contents, or raw
identity claims.

Redis 8 is available under a choice of RSALv2, SSPLv1, or AGPLv3. The local
sample pulls the unmodified official image, but selecting a license for
redistribution or a product deployment remains an owner/legal decision; this
repository's Apache-2.0 license does not make that choice on the image user's
behalf.

## What is intentionally not claimed

- Pub/Sub is not durable and no code calls it durable.
- A successful socket emit is not proof that a client received a notification.
- A stored acknowledgement proves an authorized client called the endpoint,
  not that a human saw or acted on the notification.
- BullMQ retry does not make a non-idempotent business operation safe.
- A local container test is not evidence of production capacity or failover.
- The sample delegates login, tenant membership, revocation policy, and token
  issuance to an external provider; it does not implement those systems.
- The repository has no regulated-data policy, deployment, cloud secret
  integration, backup schedule, alerting, or paid service.
- The configurable retention default is not a universal compliance or product
  requirement.
