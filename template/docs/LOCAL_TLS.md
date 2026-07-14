# Local HTTPS and the shared development CA

Local HTTPS uses one workstation-owned certificate authority (CA), not a new
self-signed certificate for every project. This keeps browser trust durable and
prevents each tool or AI agent from silently creating a different trust root.

## Non-negotiable model

```text
one owner-trusted local root
  -> one service-managed intermediate
    -> short-lived project certificates
```

- The reverse-proxy/CA service signs certificates. Agents configure routes;
  they do **not** handle signing keys or sign certificates themselves.
- Never create or trust a per-project root CA when the host already has a
  canonical local CA.
- Never read, copy, display, transmit, or commit `root.key`, `intermediate.key`,
  or any exported private key.
- Never make `-k`, `--insecure`, disabled verification, or an "accept any
  certificate" callback part of committed code or permanent configuration.
- Importing/removing a trust root, rotating the CA, or reloading the live proxy
  is an owner-approved host operation. Normal branch, review, test, rollout,
  and rollback rules still apply.

## Agent startup procedure

When a task involves local HTTPS:

1. Read `~/.config/pet-projects/local-tls.json` if it exists. It is the
   workstation's non-secret source of truth for the proxy service, persistent
   data directory, public root-certificate path, expected SHA-256 fingerprint,
   canonical config, and naming policy.
2. Inspect the process that actually serves the port. Do not assume an
   interactive shell and a background service use the same data directory.
3. Match the public root certificate's SHA-256 fingerprint to the manifest
   before changing trust. A common name is not sufficient: two roots can have
   the same name but different keys.
4. Add the project route to the canonical reverse proxy and use its internal
   issuer. Do not launch a second proxy instance with a different data
   directory.
5. Parse candidate and rollback Caddyfiles without provisioning by running
   `caddy adapt --config <file> --adapter caddyfile >/dev/null`. Review the diff,
   reload only with authorization, and verify the live URL without a TLS bypass.

If the manifest is absent, stop before creating or trusting a CA. Ask the owner
whether to adopt the existing proxy CA or establish a new workstation CA, then
record the approved public metadata in that manifest. Private keys never belong
in the manifest.

## Caddy pattern

For a Mac using one Homebrew Caddy service, the canonical service owns the root,
intermediate, and leaf lifecycle:

```caddyfile
{
	skip_install_trust
}

https://{{ project_slug }}.dev.test:8443 {
	reverse_proxy 127.0.0.1:{{ port_web }}
	tls internal
}
```

This stamped example is only for a server-based project whose web service is
actually listening on loopback port `{{ port_web }}`. Confirm the process and
health path before deployment. A browser extension or another project with no
local server needs no proxy route and no child certificate; apply this workflow
only if that project later adds a loopback service.

`skip_install_trust` is intentional after the owner performs the one-time,
fingerprint-checked trust operation. It prevents background reloads from trying
to make trust-store changes. Caddy's persistent data directory must be preserved;
starting another Caddy under a different `HOME`/`XDG_DATA_HOME` creates a second,
untrusted CA even when both roots have the same display name.

Version a project-specific Caddy snippet when useful, but deploy it into the
canonical config named by the host manifest. Preflight candidate and rollback
syntax without provisioning:

```bash
caddy adapt --config /path/to/Caddyfile --adapter caddyfile >/dev/null
```

Do **not** use `caddy validate` or `caddy adapt --validate` from an ordinary
interactive shell for a `tls internal` config. Validation provisions PKI and can
create a second root/intermediate under the shell's `HOME`/`XDG_DATA_HOME`. Let
the already-running canonical service provision during the authorized reload.
A service restart must read the same persistent config that was live-tested; an
admin-API-only reload from another file is not durable.

## One-time macOS trust procedure

The owner performs this once. Replace the examples with the exact values from
the host manifest:

```bash
ROOT_CERT=/path/from/local-tls.json
EXPECTED_SHA256=FINGERPRINT_FROM_LOCAL_TLS_JSON
normalize_sha256() {
  printf '%s' "$1" | tr -d ':[:space:]' | tr '[:lower:]' '[:upper:]'
}
EXPECTED_SHA256="$(normalize_sha256 "$EXPECTED_SHA256")"
ACTUAL_SHA256="$(normalize_sha256 "$(
  openssl x509 -in "$ROOT_CERT" -noout -fingerprint -sha256 | sed 's/.*=//'
)")"
if [ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ]; then
  security add-trusted-cert \
    -r trustRoot \
    -p ssl \
    -k "$HOME/Library/Keychains/login.keychain-db" \
    "$ROOT_CERT"
else
  printf 'Refusing trust import: root fingerprint mismatch\n' >&2
fi
```

This trusts only the public root for SSL in the current user's Login Keychain.
System-wide trust is a separate administrator-approved action. Never import a
private key. Browsers already running may need a full restart before they notice
the updated Keychain.

To inspect installed roots, compare exact fingerprints rather than names:

```bash
security find-certificate -a -Z -c 'Caddy Local Authority' \
  "$HOME/Library/Keychains/login.keychain-db"
```

## Naming

- Keep an existing `macbook-pro.local`-style name only when Bonjour/mDNS is the
  intended resolver. `.local` has special mDNS meaning.
- Prefer `<project>.dev.test` for new pet projects. `.test` is reserved for
  testing and cannot collide with a public DNS suffix.
- Add explicit local name resolution (for example, owner-managed `/etc/hosts`
  entries or a local DNS resolver). A certificate does not create DNS.
- The port is not part of a certificate name. The same trusted certificate name
  works on `443`, `8443`, or another HTTPS port when the URL includes that port.

## Verification

Success requires all of the following:

```bash
PROJECT_HOST={{ project_slug }}.dev.test
PROJECT_PORT=8443

# No -k / --insecure. Append the project's documented health path when it has one.
curl --fail --show-error --silent "https://${PROJECT_HOST}:${PROJECT_PORT}/"

# Confirm the served identity, issuer, validity, and SANs.
openssl s_client -connect "${PROJECT_HOST}:${PROJECT_PORT}" \
  -servername "$PROJECT_HOST" </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

For a project with no local server, skip certificate issuance and this live URL
check. Otherwise, also open the URL in the owner's normal browser and confirm
there is no warning.
Some Python, Node, Java, and container runtimes do not use the macOS Keychain.
Give those clients the **public root certificate** through their supported CA
bundle setting (for example `SSL_CERT_FILE`) rather than disabling verification.

## Rollback and CA compromise

Before removing trust, identify the exact installed SHA-256 fingerprint from the
host manifest. Then remove only that certificate and its user trust settings:

```bash
security delete-certificate -t -Z SHA256_WITHOUT_COLONS \
  "$HOME/Library/Keychains/login.keychain-db"
```

Removing trust does not delete Caddy's CA files; it only restores browser
warnings. If a CA private key may have been exposed, stop using the CA, remove
its trust anchor, rotate to a new root, reissue all project certificates, update
the host manifest, and document the incident. Do not quietly re-trust a copied
or unexplained root.
