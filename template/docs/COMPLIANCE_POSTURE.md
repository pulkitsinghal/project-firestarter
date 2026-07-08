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

## Data handling

- **At rest:** what's stored, where, and for how long (retention).
- **In transit:** TLS everywhere; which outbound egress is allowed.
- **Deletion / export:** how a subject's data is removed or exported, if in scope.

## Review triggers

Re-check this posture when: the data classes change, a new integration sends data
off-box, or you take on real users. Record the decision trail in
[docs/OPEN_QUESTIONS.md](OPEN_QUESTIONS.md), and see [SECURITY.md](../SECURITY.md)
for vulnerability disclosure and secret-handling rules.
