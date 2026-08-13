# notebook-crypto

Cloud-blind envelope encryption for a per-user notebook. The store holds only
ciphertext; neither the operator, the server, nor the cloud provider can read a
user's content — including in backups.

**This is public on purpose.** Its security rests only on the keys, never on the
code being secret (Kerckhoffs's principle) — so publishing it doesn't help an
attacker, and open, auditable crypto is how you *earn* the "even we can't see it"
claim instead of just asserting it.

## What it guarantees (all proven, not assumed)
- **Round-trip fidelity** — byte-exact for every field/type.
- **Server-blind at rest** — stored bytes (and DB dumps) contain no plaintext.
- **Dual-key** — a user share AND a system share are BOTH required, for the field
  encryption AND the blind index; either alone is useless. Shares are validated
  (exactly 32 bytes) so an empty/short share fails closed, never silently
  collapsing the 2-of-2. The two combine only on the user's device.
- **Recovery** — a user recovery code re-derives the user share on a new device;
  the operator still cannot decrypt. A malformed code is rejected, not
  mis-derived into a lockout.
- **Per-user blind index** — the server dedups by canonical name without reading
  it, and the same name in two notebooks produces *different* tags (no linkage).
- **Tamper-evident, no substitution** — a modified byte, or a ciphertext moved to
  another (tenant, field, row), fails closed, bound by an injective
  per-(tenant, field, row, version) AAD folded into both layers.
- **Rollback resistance is conditional** (read this): the AAD gives integrity of
  *association*, not *freshness*. A rolled-back version fails closed **only when
  the `version` (and full `RecordContext`) passed at open time comes from a
  trusted, monotonic source** — a server-side row counter under RLS, or a
  client-held monotonic clock — **never** the version stored beside the ciphertext
  and handed back by the untrusted store (that design silently rolls back). The
  library does not enforce monotonicity and cannot detect a reused/forgotten
  version bump; that is the caller's invariant.

## Primitives (standard, vetted — nothing invented)
AES-256-GCM, HKDF-SHA256, HMAC-SHA256 via `pyca/cryptography`. The same primitives
exist in Apple CryptoKit and the WebCrypto API. Known-answer vectors for the
deterministic layers (KEK, blind-index key + tag, recovery-share, canonicalize)
are committed in `tests/test_vectors.py`; the CryptoKit/WebCrypto ports (not yet
written) must reproduce them byte-for-byte before they are trusted.

## Not in here (stays private, by design)
Keys and secrets; how the system share is protected/released server-side; and the
notebook/clinical domain wiring. This library is only the reusable crypto glue.

## Test
```
python -m venv .venv && ./.venv/bin/pip install cryptography pytest 'psycopg[binary]'
./.venv/bin/python -m pytest -q          # in-memory property matrix
./scripts/mutation_check.sh              # 7 mutations prove the core guarantees are load-bearing
```
Set `NOTEBOOK_CRYPTO_PG_DSN` to also run the real-Postgres sample-DB harness.
