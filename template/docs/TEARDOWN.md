# Teardown — scope it to every control plane, not the primary resource

<!-- teardown-lane:start -->
Teardown is scoped to the union of control planes provisioning touched, not the
primary resource. Deleting the VM, container, function, or deploy does not by
itself revoke the DNS record, TLS certificate, mesh enrollment, service account,
OAuth grant, webhook, or CI secret that standing it up created. Enumerate that
union at provisioning time, and make teardown assert each plane is gone rather
than assuming the primary delete cascaded. Edit the inventory below to match
{{ project_name }} — the cross-plane discipline is the reusable part.

Teardown of a provisioned resource is an owner-gated, live, destructive external
action. It is never self-authorized by default: route it through the
`owner-action` hand-off and the preview-first irreversible-action precept in
[`../AGENTS.md`](../AGENTS.md) — preview the exact planes and deletions, obtain
fresh scope-bound authorization, then record a sanitized outcome. The one mirror
of the self-authorized deploy lane is a throwaway resource this session itself
provisioned that holds no state and no externally-trusted grant and can be
recreated identically; anything that deletes shared, stateful, or
externally-trusted state stays owner-gated.

## Why the primary delete is not the whole job

Provisioning almost never touches one system. A single "stand up an exit node"
step enrolls a node in a mesh identity plane *and* creates a VM in a cloud
provider; a teardown that deletes only the VM leaves the enrollment behind. The
residue is not merely untidy:

- **A trusted identity must not outlive the resource it was issued for.** A grant
  issued for a resource — a node key, a service-account key, an OAuth grant, a
  deploy token — is a standing authority. When the resource is deleted and the
  grant is not revoked, that authority is still live and now attached to nothing
  the owner controls. The provider may reissue the underlying address or handle
  to someone else while the stale grant still trusts it.
- **The inventory and reality have diverged, silently.** An offline device, a
  dangling DNS record, or an idle bucket reads to the next operator as capacity
  that exists and is merely down — not as residue. Nothing surfaces the gap.
- **Spend reaching zero is not proof of teardown.** The teardown that "stops all
  spend" is precisely why the residue survives: the cost signal that would
  surface a leftover plane is the one thing that went to zero. A zero bill proves
  the metered resource stopped and says nothing about the unmetered grants,
  records, and enrollments beside it.

This is the standing-authority risk that credential rotation
([`SECURITY_INCIDENT_ROTATION.md`](SECURITY_INCIDENT_ROTATION.md)) addresses from
the opposite trigger. Rotation handles a credential that leaked. Teardown handles
a credential that never leaked and was never revoked, because the thing it
authenticated was deleted and nobody revisited the grant — the same
standing-authority risk, opposite trigger. One is an incident; the other is
routine cleanup, which is why it goes unnoticed.

## The control-plane inventory

Name every plane provisioning touched *at provisioning time*, so teardown reads
an inventory instead of reconstructing one from memory. For each plane, record
what provisioning created, how to verify it is gone, and who may delete it.

| Control plane | What provisioning created | How to verify it is gone | Who can delete it |
|---|---|---|---|
| Compute / the primary resource | VM, container, function, or deploy | the provider lists no instance and the endpoint no longer answers | owner-gated; self-authorized only for a throwaway resource this session provisioned (the deploy lane's mirror) |
| DNS | A/AAAA/CNAME records, delegated zones | an authoritative lookup returns NXDOMAIN and no stale record points at a reclaimable address | owner-gated (account / DNS plane) |
| TLS / PKI | issued certificates and their ACME accounts | the certificate is revoked or expired and the ACME account is deactivated | owner-gated |
| Network policy | ingress/egress and security-group rules, allowlisted addresses | the rule is absent and none references the freed resource | owner-gated |
| Mesh / VPN identity | an enrolled node or peer, often with key expiry disabled | the admin console shows no device and the node key is revoked | owner-gated |
| Identity & access | service principals and every key, app grant, or token issued to them | the principal is deleted and every issued key revoked | owner-gated |
| Registries & storage | pushed images and provisioned storage buckets | image tags are deleted and the bucket is emptied and removed | owner-gated |
| Observability | log and metric sinks, alert targets, recurring jobs | the sink/target is removed and no job still references the resource | owner-gated |
| Integrations | registered callback endpoints and injected secrets | the endpoint is deregistered and the secret is deleted from its store | owner-gated |
| Sharing / access-grant | share links, reviewer invites, external access grants | every grant is listed and revoked and no link still resolves | owner-gated |

## Residue checklist

Walk this on every teardown; it is the same set everywhere and is never one
system. Mark each plane **gone** or **outstanding** — never leave it blank:

- [ ] DNS records
- [ ] TLS certificates and their ACME accounts
- [ ] firewall / security-group rules
- [ ] mesh or VPN enrollments
- [ ] service accounts and their keys
- [ ] OAuth app grants
- [ ] container or artifact-registry images
- [ ] object-storage buckets
- [ ] log sinks
- [ ] monitoring targets
- [ ] webhooks
- [ ] scheduled jobs
- [ ] CI secrets
- [ ] the sharing and access-grant plane

## Fail closed when a plane cannot be verified

An unverifiable plane is recorded as outstanding, never as clean. If a
credential-less session, a missing admin scope, or an unreachable console means
teardown cannot confirm a plane is gone, that plane stays on the outstanding list
and routes to the `owner-action` hand-off; assuming the primary delete cascaded
is exactly the failure this lane exists to prevent. A teardown is complete only
when every enumerated plane is proven gone, or is explicitly left in place with
owner acceptance of the standing grant. A plane that was never checked is
outstanding, not clean.

## Related runbooks

- [`DEPLOY_POLICY.md`](DEPLOY_POLICY.md) — the reciprocal obligation: whatever a
  deploy path stands up, it names its planes at provisioning time.
- [`../AGENTS.md`](../AGENTS.md) — the `owner-action` hand-off and the
  preview-first irreversible-action precept teardown routes through.
- [`SECURITY_INCIDENT_ROTATION.md`](SECURITY_INCIDENT_ROTATION.md) — the same
  standing-authority risk reached from the leaked-credential trigger.
- [`GO_LIVE.md`](GO_LIVE.md) — the stand-up checklist whose lifecycle this closes.
<!-- teardown-lane:end -->
