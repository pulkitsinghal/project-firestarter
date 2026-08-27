# Cloud database recovery

This stack ships an opt-in, Docker-only recovery path for the application-owned
`public` schema:

- create a custom-format PostgreSQL snapshot in private S3-compatible storage;
- prove its bytes, manifest, and post-upload SHA-256 before marking it ready;
- require that verified recovery point before incremental cloud migrations; and
- restore one exact snapshot only into an attested, empty isolated drill target.

It deliberately does **not** ship a generic production-restore button. A live
restore needs project-specific writer fencing, queue/job handling, accepted
write loss, an isolated drill, application/data checks, and external-effect
reconciliation under [`ROLLBACK.md`](ROLLBACK.md).
Those controls cannot be inferred safely from a starter.

## Coverage boundary

The logical archive contains schema, data, and row-level-security policies in
`public`; ownership, object grants, and extension-owned objects are omitted for
portable restore. The isolated target must precreate required roles/extensions,
and the referenced project verification plan must re-establish and test the
intended least-privilege grants. It does not cover managed
`auth`/`storage` schemas, Storage object bytes, provider configuration, Edge
Functions, keys, webhooks, queues, caches, or other external systems. Supabase's
[backup guide](https://supabase.com/docs/guides/platform/backups) likewise notes
that database backups contain Storage metadata rather than the stored objects.

If the application owns another schema, or `public` is not independently
restorable, do not use these commands as recovery proof. Choose managed backup,
PITR, or a reviewed project-specific snapshot adapter in
`docs/OPEN_QUESTIONS.md` first.

## Configuration contract

Inject runtime values from the owner-managed secret/configuration system. Never
commit them, put values in a Make argument, or paste them into an issue or log.

| Variable | Meaning |
|---|---|
| `CLOUD_DB_HOST`, `CLOUD_DB_PORT` | Bounded DNS hostname and port; port defaults to `5432` |
| `CLOUD_DB_NAME`, `CLOUD_DB_USER` | Bounded database and role names |
| `CLOUD_DB_PASSWORD` | Database password; forwarded only as the `PGPASSWORD` environment-variable name |
| `CLOUD_DB_TARGET_ID` | Opaque, non-secret identity for the exact database target |
| `CLOUD_DB_CONNECTION_MODE` | `direct` or `session`; transaction pooling is refused |
| `CLOUD_DB_SSLMODE` | Must be `verify-full`; unauthenticated database TLS is refused |
| `CLOUD_DB_SSLROOTCERT_FILE` | Optional safe project-relative committed PEM CA; otherwise the PostgreSQL client uses system roots |
| `CLOUD_DB_ARCHIVE_ID` | Opaque, non-secret identity for the archive configuration |
| `CLOUD_DB_ARCHIVE_BUCKET` | Existing private bucket; the scripts never create or make it public |
| `CLOUD_DB_ARCHIVE_PREFIX` | Optional safe relative prefix; default `db-snapshots` |
| `CLOUD_DB_S3_PROVIDER` | rclone S3 provider name; default `Other` |
| `CLOUD_DB_S3_ENDPOINT` | Required for non-AWS S3-compatible storage |
| `CLOUD_DB_S3_CA_CERT_FILE` | Optional safe project-relative committed PEM CA for a private HTTPS endpoint |
| `CLOUD_DB_S3_REGION` | Optional region; default `us-east-1` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Archive credentials; values are forwarded by environment-variable name |
| `CLOUD_DB_MAX_SNAPSHOT_BYTES` | Owner-reviewed hard byte cap; default 1 GiB |
| `CLOUD_DB_MAX_RESTORE_SQL_BYTES` | Owner-reviewed cap for the rendered restore program; default 4 GiB |
| `CLOUD_DB_AUTHORIZATION_PUBLIC_KEY_FILE` | Safe project-relative path to the committed owner public key; never a private key |
| `CLOUD_DB_AUTHORIZATION_SIGNATURE` | Detached base64 signature over the exact canonical authorization statement; not a credential |
| `CLOUD_DB_TARGET_ATTESTATION` | Opaque evidence reference for an isolated drill target |
| `CLOUD_DB_VERIFICATION_PLAN` | Opaque reference to the project-specific post-restore checks |

Use a direct connection or the session pooler. Supabase's current
[migration guidance](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres)
recommends session mode for dump/restore when direct connectivity is not used.
The pinned PostgreSQL client refuses a newer server major instead of attempting
an unreviewed compatibility path.

Credential-bearing connection URIs are intentionally unsupported. Discrete
libpq environment fields keep the password out of Docker and PostgreSQL process
arguments and prevent URI query options from overriding the reviewed TLS mode.
Hostname verification is mandatory. A private/self-signed database endpoint
must use a committed public CA file; never commit a client key or password.

The endpoint must be HTTPS. The archive must be private, versioned/immutable,
encrypted, retained through the rollback window, and governed by
least-privilege write/read credentials. The scripts use non-overwriting writes,
bounded read-back proof, and publish a `.ready` marker last, but provider
retention/object lock and protection of the archive-writer credential remain
owner configuration. SHA-256 detects corruption; it does not authenticate data
against a malicious holder of that credential.

## Preview and one-use authorization

Every safe Make target defaults to a plan or read-only preparation. Ordinary
preview creates no local state and calls neither Docker nor a remote service.

```bash
make cloud-snapshot
make cloud-migrate
make cloud-restore SNAPSHOT=<exact-ready-name>
```

`cloud-snapshot --prepare`, `cloud-migrate --prepare`, and
`cloud-restore --prepare` are explicitly read-only live discovery: they need
owner-injected credentials, resolve the target state, and print an exact
`scope_sha256`. They do not write a snapshot, database, archive, or durable
journal.

Execution requires all five fresh values below. They are a short-lived,
scope-bound owner decision. The owner signs the canonical statement printed by
preparation outside the execution process; execution verifies it against a
committed public key in the clean reviewed revision. Never commit or inject the
private key. The identifier must be unique; its hash is consumed atomically in
the current checkout before the first external write. The exact operation's
state still prevents a successful replay from another checkout, but the trusted
signer must also maintain its own durable authorization-ID ledger.

The committed file contains only the public verification key. The signer keeps
the private key outside the repository and signs these exact LF-terminated
bytes (including the final newline):

```text
format=firestarter-cloud-db-authorization-v1
operation=<snapshot-create|cloud-migrate|isolated-restore-drill>
scope_sha256=<exact prepared scope>
authorization_id=<fresh opaque ID>
expires_at=<the prepared Unix expiry>
reference=<the prepared exact snapshot name>
```

Use an approved owner-side signer (equivalent to `openssl dgst -sha256 -sign`)
and inject only its base64 signature. Firestarter verifies with the
version-and-digest-pinned OpenSSL container; the private key is never present.

```text
CLOUD_DB_PLAN_NONCE
CLOUD_DB_APPROVAL_EXPIRES_AT
CLOUD_DB_AUTHORIZATION_ID
CLOUD_DB_APPROVED_SCOPE
CLOUD_DB_AUTHORIZATION_SIGNATURE
```

The expiry may be at most 15 minutes away. `--execute` only arms the command; a
missing, stale, changed-scope, or replayed authorization fails closed. Sanitized
intent/outcome state lives under the gitignored
`.firestarter/cloud-db-recovery/`. An interrupted or unjournaled outcome is
`indeterminate`: inspect the exact snapshot/database state before seeking a new
authorization.

## Snapshot workflow

1. Run `make cloud-snapshot` for the credential-free local preview, then run
   `make cloud-snapshot-prepare` with read credentials. Review its exact nonce,
   expiry, byte cap, opaque and database-derived target identity, archive
   identity, source revision, migration-set digest, and immutable image pins.
2. Run `make cloud-snapshot-execute` with configuration and authorization
   already injected.
3. The script verifies the detached owner signature, records a sanitized intent,
   rechecks the committed source and stable database identity. A read-only
   controller transaction checks that identity on the exporting connection and
   exports the exact consistency snapshot consumed by a transfer-bounded
   `pg_dump -Fc` for `public`. It excludes ownership, grants, and extension-owned
   objects, checks the archive with `pg_restore --list`, and computes SHA-256.
4. It uploads the archive and manifest under a generated non-overwriting name,
   downloads the remote bytes for checksum proof, publishes `.ready` last, and
   reads that marker back before reporting the snapshot ready.

The manifest binds opaque environment/archive identities, a database-derived
cluster/database identity, connection mode, schema, source/config/migration
revisions, server and client versions, byte count, checksum, reason, and
creation time. Mutable database inventories are deliberately not sampled on
separate connections and misrepresented as belonging to the dump's consistency
point. It contains no URL, credential, account identifier, production row,
person, or project-specific operational detail.

`make cloud-snapshot-list` lists published readiness evidence. It is not a
substitute for restore-time verification: restoration revalidates the marker,
manifest, archive bytes, size, checksum, and format. Restoration never accepts
`latest`; the owner must authorize one exact immutable snapshot.

## Cloud migration workflow

`make migrate` remains the local Compose path. Cloud migration is separate and
incremental; it never dumps the local schema into a managed database.

1. Run `make cloud-migrate` for a credential-free local preview.
2. With read credentials injected, run `make cloud-migrate-prepare`. Review the
   exact pending migration digest/list and pre-migration snapshot name.
3. Provide fresh one-use authorization for that scope and run
   `make cloud-migrate-execute`.
4. The command writes intent, creates and remotely verifies the snapshot, then
   rechecks migration state. Any drift blocks migration.
5. The exact approved migration bytes are copied into a private read-only stage
   before the snapshot. A pinned, networkless SQL lexical guard rejects psql
   meta-commands, transaction control, and malformed/oversized input that could
   escape `--single-transaction`. One advisory- and table-locked PostgreSQL
   transaction rechecks the signed database identity on its own writer
   connection, compares history as sets, applies only that staged ordered set,
   and records rows with plain conflict-failing inserts. A failed or
   indeterminate snapshot always blocks migration; there is no skip/break-glass
   flag in this generic path.

## Isolated restore drill

Provision a disposable target whose app-owned `public` scope is empty. Precreate
the required roles/extensions and set a distinct opaque target identity plus:

```text
CLOUD_DB_TARGET_KIND=isolated-drill
```

Then:

1. Run `make cloud-restore-prepare SNAPSHOT=<exact-ready-name>` with
   `--target-attestation <evidence-id>` and
   `--verification-plan <evidence-id>` (or pass those through the script
   directly). Preparation verifies the ready marker/manifest, both opaque and
   database-derived source/destination separation, and an empty destination
   (relations, functions, and types).
2. Review the exact scope; supply fresh one-use authorization.
3. Run `make cloud-restore-drill SNAPSHOT=<exact-ready-name>` with the same
   evidence references already supplied to the script.
4. The archive is downloaded with a hard transfer cap, then
   size/checksum/format verified. `pg_restore` must render a complete bounded SQL
   program before any target write; only then does `psql` recheck both the
   signed database identity and app-scope emptiness on its writer connection and
   apply it in one transaction without creating extensions,
   applying archive grants, or cleaning an existing schema. The attested drill
   target must remain isolated from every other writer throughout the run.
5. The script records `pending/application-verification-required`, never
   `verified`. Re-establish intended grants and run the referenced project-
   specific application, data-integrity, authorization, and reconciliation
   plan before accepting the drill.

A green isolated drill is evidence for the production runbook; it is not live
restore authorization. The production runbook must still fence writers, record
the final high-water mark, quantify and accept the write-loss window, preserve
a safe pre-restore point when appropriate, reconcile external effects, and
verify the real application before reopening writes.

## Failure rules

- Never retry an `indeterminate` upload, migration, or restore blindly.
- Never reuse an authorization identifier.
- Never weaken TLS, use transaction pooling, restore `latest`, or point the
  drill command at its source target.
- Never call a snapshot “ready” without archive + manifest + verified checksum
  + final readiness marker.
- Never call a restore “verified” from archive replay alone; project-specific
  application/data/security verification remains mandatory.
- Never treat this app-schema archive as a backup of managed/provider/external
  state.
