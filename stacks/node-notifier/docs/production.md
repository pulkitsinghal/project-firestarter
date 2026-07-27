# Production starter guide

This guide describes the production contract implemented by {{ project_name }}. It
does not provision or deploy an identity provider, Redis, TLS endpoint, secret
manager, load balancer, monitoring system, or backup system.

## Security model

The API is an OAuth-style resource server. A trusted external identity provider
issues short-lived JWT access tokens. The application validates each token
against one configured HTTPS JWKS endpoint and requires:

- a signature from an explicitly allowed asymmetric algorithm;
- the exact configured issuer and audience;
- a valid expiration;
- a non-empty `sub` claim; and
- a non-empty configured tenant claim, `tenant_id` by default.

The API HMACs `(tenant, subject)` into opaque Redis owner and Socket.IO room
keys. Raw tenant and subject claims are not written into queue data. A refreshed
token or another device for the same pair resolves to the same owner. Different
users or tenants cannot read or acknowledge each other's tasks.

This service does not decide whether the subject belongs to the tenant. The
identity provider and its authorization policy must make and maintain that
decision. Use access tokens targeted to this API, not ID tokens intended for a
browser client.

## Required configuration

Production starts only when all required security settings are present:

```dotenv
NODE_ENV=production
HOST=0.0.0.0
PORT=3000
PUBLIC_ORIGIN=https://{{ project_slug }}.example

AUTH_MODE=oidc
OIDC_ISSUER=https://identity.example/
OIDC_AUDIENCE=https://{{ project_slug }}.example/api
OIDC_JWKS_URL=https://identity.example/.well-known/jwks.json
OIDC_ALGORITHMS=RS256
OIDC_TENANT_CLAIM=tenant_id

SESSION_SECRET=<at-least-32-random-bytes-from-a-secret-manager>
REDIS_URL=rediss://{{ project_slug }}:<url-encoded-password>@redis.example:6380/0

TASK_RETENTION_SECONDS=86400
TASK_RATE_LIMIT=30
TASK_RATE_WINDOW_SECONDS=60
REPLAY_LIMIT=50
WORKER_CONCURRENCY=4
```

`SESSION_SECRET` is the HMAC key for opaque owner and room identifiers even
though production does not use the anonymous cookie. Rotating it makes
previously indexed tasks inaccessible, so rotation requires an explicit
migration or acceptance that retained notifications will expire unread.

The allowed JWT algorithms are `RS256`, `PS256`, `ES256`, and `EdDSA`. Keep the
allowlist as narrow as the provider permits. The issuer, audience, JWKS URL,
tenant claim, and algorithm list are configuration, not values accepted from a
request or token header.

## Client contract

Acquire the access token through the application's existing authorization-code
flow. Send it in the HTTP authorization header and Socket.IO handshake data:

```js
const accessToken = await acquireAccessToken();

const response = await fetch("/api/tasks", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ message: "Prepare report" }),
});

const socket = io({
  auth: { token: accessToken },
  transports: ["websocket"],
});
```

Do not place access tokens in URLs, logs, local storage, task messages, or
queue payloads. Refresh a token through the identity SDK and reconnect the
socket before expiration. The server disconnects a socket when the token used
for its handshake expires.

Available task routes:

- `POST /api/tasks` creates a rate-limited job and returns `202`.
- `GET /api/tasks?limit=50` lists recent tasks owned by the identity.
- `GET /api/tasks/:id` reads one owned task.
- `POST /api/tasks/:id/ack` records the first terminal acknowledgement.

Cross-owner reads return `404`, avoiding a task-existence oracle.

## Delivery semantics

BullMQ job state and result are authoritative. Pub/Sub and Socket.IO are
at-most-once wake-ups.

When a socket connects, the API replays recent completed or failed tasks that
do not have an acknowledgement. Acknowledgement uses an idempotent first-write
receipt: repeated calls return the original `acknowledgedAt`.

The receipt proves that an authorized client called the endpoint. It does not
prove that a person saw, understood, or acted on a notification. Products that
need those claims require additional workflow state and audit policy.

`TASK_RETENTION_SECONDS` applies to BullMQ terminal jobs, identity indexes, and
acknowledgements. It accepts 300 seconds through 30 days. Choose the value from
product recovery requirements, data classification, storage capacity, and
deletion policy.

The fixed-window task creation limit is shared through Redis and scoped to the
opaque owner key. A rejected request returns `429`, `Retry-After`, and rate
limit metadata. It protects task creation, not bandwidth, authentication, or
global denial-of-service boundaries; enforce those at the edge too.

## Redis TLS and ACL boundary

Production rejects `redis://` and URLs without both an ACL username and
password. `rediss://` enables server certificate verification with Node's
trusted roots.

For a private certificate authority or mutual TLS, mount read-only files:

```dotenv
REDIS_CA_FILE=/run/secrets/redis-ca.pem
REDIS_CERT_FILE=/run/secrets/redis-client.pem
REDIS_KEY_FILE=/run/secrets/redis-client-key.pem
```

The certificate and key must be configured together. Keep their contents and
the URL password in a secret manager; never commit them.

Create a named Redis user limited to this application's key and channel
prefixes. BullMQ uses `bull:<queue-name>:*`; this application also uses
`<queue-name>:*` and `<event-channel>`. A starting ACL shape is:

```text
user {{ project_slug }} reset on >LONG_RANDOM_PASSWORD \
  ~bull:{{ project_slug }}:* ~{{ project_slug }}:* \
  &bull:{{ project_slug }}:* &{{ project_slug }}:events \
  +@connection +@read +@write +@scripting +@pubsub +info -@dangerous
```

Command categories can change as Redis and BullMQ evolve. Validate the exact
rule with Redis `ACL DRYRUN`, the repository integration suite, and the chosen
managed service; do not grant `+@all` merely to bypass a failed test. Keep
Redis on a private network and configure backups, restore exercises,
availability, memory policy, monitoring, and alerting separately.

## Health and scaling

- `/health/live` proves the process can answer HTTP.
- `/health/ready` requires a Redis `PING`; remove an instance from routing when
  it returns `503`.
- API replicas subscribe to the shared completion channel and use
  WebSocket-only transport, avoiding long-polling stickiness.
- Workers may scale independently, but downstream operations must be
  idempotent and concurrency must be capped to downstream capacity.

Set reverse-proxy timeouts for WebSockets, preserve the exact public Origin,
terminate current TLS, and bound request size at both the edge and application.

## Pre-deployment gate

Before deploying:

1. choose and test the identity provider's tenant-membership and revocation
   behavior;
2. configure HTTPS, secret injection, the Redis ACL/TLS connection, backups,
   restore tests, capacity, and alerting;
3. choose retention, rate limits, acknowledgement meaning, data
   classification, and deletion/audit policy;
4. replace the simulated worker with an idempotent operation;
5. run unit, Redis integration, container, load, failure, and rollback tests;
6. review the applicable Redis 8 license; and
7. identify a rollback target before changing production.

No deployment configuration or paid resource is created by this repository.

## Browser-extension clients

Manifest V3 service workers are suspended, so do not treat a permanent socket
in an extension background worker as a delivery guarantee. A side panel may
hold the low-latency Socket.IO connection while visible, but it must reconcile
`GET /api/tasks` whenever it opens, resumes, or refreshes credentials.

The starter currently enforces same-origin browser writes and Socket.IO
handshakes; it does **not** ship permissive cross-origin headers. An extension
must therefore call through an authorized same-origin gateway, or add and test
an exact `chrome-extension://<released-extension-id>` allowlist for HTTP
preflights and WebSockets. Never use `*` with authorization headers, never
reflect arbitrary request origins, and keep non-browser bearer clients
separate from cookie/CSRF assumptions.

Keep the provider-issued access token in the extension's existing
authentication lifecycle; do not copy the anonymous tutorial cookie model into
an extension. Before enabling a real endpoint, review the host permission,
Content Security Policy, identity audience, tenant claim, privacy disclosure,
retention, and user-facing acknowledgement semantics. A feature branch may
ship the disabled client adapter and synthetic tests without authorizing any
production connection.
