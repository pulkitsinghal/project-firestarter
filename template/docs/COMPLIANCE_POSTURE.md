# Compliance & Privacy Posture

_Not legal advice — confirm any determination with qualified counsel._

A short, honest statement of which regulatory regimes {{ project_name }} is (and
is **not**) in scope for, and the controls that keep it there. Fill this in
early; revisit whenever the data you handle changes. An explicit "we are out of
scope, and here's why" is worth far more than silence.

## Stance

State the posture in one paragraph. The strongest posture is usually to stay
**out of scope entirely** rather than build a compliant system for regulated
data — e.g. "we only ever process de-identified or synthetic data, so <regime>'s
obligations don't attach." If you must handle regulated data, name the regime
(GDPR, HIPAA, PCI-DSS, SOC 2, CCPA, …) and who the responsible party is.

## What counts as sensitive here

Define the sensitive-data class for this project (PII, PHI, cardholder data,
credentials, location traces…) and the specific identifiers that trigger scope,
so "sensitive" is concrete and testable rather than a vibe.

## Controls (enforced in code)

Keep this a table of **risk → control → where**, each row pointing at real
code/config so the control is auditable — not aspirational:

| Risk | Control | Where |
|---|---|---|
| _e.g._ a user submits regulated data | input gate rejects or redacts it | `backend/...` |
| regulated data reaches a third party (e.g. an LLM) | scrub before any egress | `backend/...` |
| SSRF / scraping an internal host | egress host must be public; allowlist | `backend/...` |
| secrets committed to the repo | gitleaks secret scan (required check) | `.github/workflows/secret-scan.yml` |
| local/session output or PII-shaped content staged | immutable-index, content-suppressed offline tripwire | `scripts/repo-hygiene.sh` / `make repo-hygiene` |

## Artifact policy (declared, not just scanned)

`scripts/repo-hygiene.sh` scans for *suspicious shapes* — credentials, PII,
forbidden paths. That answers "no bad shapes were found." It does **not** answer
"every artifact is the class it was meant to be", and only the second claim
survives encryption: once a path is git-crypt ciphertext, a shape scan sees
random bytes and can neither confirm it is clean nor flag it.

So this repo declares a disposition per artifact class in
[`artifact-policy.json`](../artifact-policy.json) — `source`, `generated`,
`encrypted-local`, `ignored-local` — and the hygiene gate enforces the
encrypted-local class against `.gitattributes` (the index scan reads committed
**blobs**, so an encrypted file arrives as ciphertext):

| Committed blob | Declared `filter=git-crypt`? | Disposition |
|---|---|---|
| git-crypt ciphertext | yes | **covered-by-encryption** — a named class, neither clean nor a finding; never scanned as content |
| git-crypt ciphertext | no | finding `encrypted-path-not-declared` — an undeclared encrypted artifact |
| plaintext | yes | finding `plaintext-at-encrypted-path` — the protection the policy promised is not in force |
| plaintext | no | the ordinary shape scan |

This is why enabling `addons/encrypted_local_areas` does not quietly blind the
gate rather than fix it: see `docs/ENCRYPTED_LOCAL_AREAS.md` when that add-on is
enabled. A project with no git-crypt declaration and no ciphertext never leaves
the ordinary scan, so the behaviour is inert until encryption is actually in use.

## Dated classification audit

"We looked at every artifact and each one is where it belongs" is worth little as
a memory and a great deal as a committed, dated record. When you run a
classification pass, write it to `audits/local-artifact-classification-<date>.json`
and commit it, so the next audit is a diff rather than a fresh act of trust.

## Data handling

- **At rest:** what's stored, where, and for how long (retention).
- **In transit:** TLS everywhere; which outbound egress is allowed.
- **Deletion / export:** how a subject's data is removed or exported, if in scope.

## Review triggers

Re-check this posture when: the data classes change, a new integration sends data
off-box, or you take on real users. Record the decision trail in
[docs/OPEN_QUESTIONS.md](OPEN_QUESTIONS.md), and see [SECURITY.md](../SECURITY.md)
for vulnerability disclosure and secret-handling rules.
