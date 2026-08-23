# Secret exposure response and rotation

Use this runbook when a password, API token, signing key, connection string,
service credential, encryption key, or other secret may have reached an
unauthorized place. **Untracking, deleting, or hiding the value is not
rotation. Treat it as compromised until the old credential is invalid and every
consumer is proven on a replacement.**

This file is safe to commit only while it remains **value-free**. Never paste a
secret, connection string, private key, session cookie, one-time code, recovery
code, or unredacted provider output here. Names, hosts, account identifiers, and
store locations can also reveal architecture: use opaque item IDs below and
keep sensitive inventory and evidence in a private security advisory or another
owner-approved restricted record.

## Authority boundary

- Provider logins; access to live secret values; rotation/revocation; production
  configuration and secret-store changes; restarts/redeploys; session
  invalidation; IAM/network changes; artifact/cache deletion; and git-history
  rewriting are **owner actions**. Agents may prepare a value-free inventory,
  identify consumers, propose commands with placeholders, and verify non-secret
  evidence without opening a provider console or handling a credential.
- If abuse may be active, prioritize containment. Revoke first even if it causes
  an outage, **except when destroying a decryption/key-encryption key would make
  required data unrecoverable**. Stop new use and restrict access to that key,
  preserve controlled decryptability, rewrap/re-encrypt, prove restore/recovery,
  and only then disable or destroy it. Otherwise use a controlled cutover:
  create replacement → propagate → reload → verify replacement → revoke old.
- Do not retrieve an exposed value from git history, logs, chat, or an artifact
  merely to test it. Verify revocation through the credential authority or an
  owner-approved, minimally scoped probe that does not print the value.

## 1. Declare and scope the incident

- [ ] Open a private incident record; do not use a public issue.
- [ ] Record detection time, exposure window, reporter, response owner, and a
      safe reference. Keep sensitive evidence in the restricted record.
- [ ] Identify every exposed credential and every alias or derived credential.
      A connection string can expose both a password and infrastructure details;
      a signing-key leak can compromise every token or artifact it signed.
- [ ] Search all plausible exposure surfaces: current files and git history,
      branches/tags, forks/clones, PR patches, chat and tickets, CI logs and
      artifacts, caches, release assets, container layers, backups, screenshots,
      and copied local files.
- [ ] Decide whether notification, legal, contractual, privacy, or provider
      escalation duties apply. Track those decisions privately.

Use one row per credential. Never put a value or a reversible encoding here.
If even the metadata is sensitive, keep only the opaque item ID in this file.

| Item ID | Class / aliases / derived items | Authority | Consumers / verifiers / caches | Mutable stores | Cutover / overlap deadline | Owner | Status |
|---------|---------------------------------|-----------|-------------------------------|----------------|----------------------------|-------|--------|
| `SEC-001` | `<restricted reference>` | `<restricted reference>` | `<restricted reference>` | `<restricted reference>` | `<safe summary + deadline>` | `<role>` | `scoped` |

## 2. Contain before expanding the blast radius

- [ ] Disable active sessions, keys, identities, or network paths immediately if
      misuse is suspected. Availability does not outrank an active compromise.
- [ ] Freeze unrelated deploys and credential changes long enough to make the
      inventory authoritative; preserve provider audit logs without copying
      secrets into the incident record.
- [ ] Reduce permissions and reachability while rotating: remove broad network
      allowlists, require TLS, prefer private connectivity, and narrow the
      replacement to one purpose and the minimum required grants.
- [ ] Remove hardcoded, demo, or guessable fallback values. Missing production
      configuration must fail closed instead of silently selecting a known key.

## 3. Rotate and propagate each item

Repeat this checklist for every row. Do not mark a family complete because one
environment, alias, or store was updated.

- [ ] Choose the cutover order. Use revoke-first for suspected active abuse;
      otherwise use a bounded overlap only when the provider supports it and a
      rollback/maintenance plan exists.
- [ ] Before a bounded overlap, record its deadline, success criteria for every
      consumer/verifier, and the stop/rollback decision. If replacement checks
      fail, stop the cutover and do not revoke the working credential unless
      active compromise makes immediate revocation the safer choice.
- [ ] Create the replacement at the credential authority with least privilege.
      Use the provider's trusted UI or feed CLI input through stdin/file
      descriptor. Never put the value in argv, shell history, logs, chat, a
      command transcript, a tracked file, or this checklist.
- [ ] Update every **mutable** durable store and runtime injection path the
      consumer can read: production, staging, development, CI, scheduled jobs,
      hosts, secret managers, password managers, and recovery stores as
      applicable. Do not rewrite or delete immutable backups as propagation.
- [ ] Cross-check stores using non-secret evidence. A fingerprint is acceptable
      only for high-entropy material and only where policy permits; never commit
      a fingerprint that would make a low-entropy secret easier to guess.
- [ ] Reload or redeploy every consumer so no process continues using cached
      credentials. Account for workers, queues, cron jobs, replicas, and old
      revisions—not just the foreground service.
- [ ] Prove the replacement works through the smallest safe health or
      authentication check. Logs and screenshots must redact credential material.
- [ ] For encryption or key-encryption keys, preserve controlled decryptability,
      rewrap/re-encrypt, and prove restore/recovery **before** the general
      revocation step below. Never destroy the only recovery path; changing a
      runtime variable is not key retirement.
- [ ] Revoke, disable, delete, or version-off the old credential at its authority.
- [ ] Prove the old credential is rejected without recovering it from an exposed
      artifact. Record only time, authority result, and safe evidence reference.
- [ ] For signing/session secrets, enumerate every derived token/artifact and
      every verifier, including cached key sets, trust stores, offline verifiers,
      and old revisions. Refresh their trust state, invalidate affected sessions
      or artifacts, and record verifier-by-verifier negative-validation evidence.
- [ ] For webhooks, database credentials, and providers that do not support two
      valid credentials, plan a provider-supported overlap or a controlled
      outage. Never assume updating one environment variable completes rotation.

## 4. Verify the whole system

- [ ] Every inventory row is `old rejected / replacement healthy`, not merely
      `replacement created`.
- [ ] Each environment and consumer uses the intended version; no retired host,
      old deployment, or job can reintroduce the compromised value. Immutable
      backups that may contain it are inventoried, access-restricted or
      quarantined, assigned a retention/expiry decision, and covered by a
      restore procedure that rotates before reconnecting restored workloads.
- [ ] Provider audit logs were reviewed for use during the exposure window, with
      findings kept in the private incident record.
- [ ] Current tracked files and build inputs pass `make secret-scan` where that
      target exists. This scan is a backstop; it does not prove historical copies
      are gone and it does not replace revocation.
- [ ] Tests cover missing-secret failure, removal of weak fallbacks, and any
      rotation-sensitive behavior without using production values.
- [ ] Network access and service-account grants are no broader than required.

## 5. Treat history cleanup as follow-up hardening

Rotation and revocation are the remedy. A `git filter-repo`/BFG rewrite or other
history purge is optional hardening and **never a substitute**: existing clones,
forks, caches, artifacts, backups, and screenshots cannot be recalled by a
force-push.

History rewriting is an owner-approved destructive operation. Coordinate a
write freeze and enumerate every ref and mirror. Before rewriting, preserve all
required forensic/legal evidence—including sensitive originals when required—in
an owner-approved restricted immutable record. Remove credential material from
public/repository reach; do not destroy evidence subject to investigation or
legal hold. Then invalidate caches/artifacts, notify collaborators to re-clone,
and verify the rewritten remote. Expect commit hashes and open work to change.
Do not run a history rewrite from this checklist automatically.

## 6. Close with evidence and prevention

- [ ] The owner confirms every old credential is invalid and every replacement
      consumer is healthy.
- [ ] The private record contains the complete inventory, safe timestamps,
      provider evidence, impact assessment, notifications, and remaining risk.
- [ ] The committed record contains no credential material or competitively
      sensitive architecture; use `withheld: sensitive incident` when needed.
- [ ] Add preventive controls: least privilege, shorter lifetime, separate
      credentials per purpose/environment, fail-closed config, log redaction,
      secret scanning, and a rehearsed rotation owner/cadence.
- [ ] Capture incident detail in `docs/postmortems/` only at a safe level. If the
      incident earned a durable project rule, promote that rule—not the sensitive
      story—to `docs/PRACTICES.md`.
