"""notebook-crypto — cloud-blind envelope encryption for a per-user notebook.

Standard primitives (AES-256-GCM, HKDF-SHA256, HMAC-SHA256), composed into a
dual-key envelope where a user share and a system share are BOTH required to
decrypt, plus a per-user blind index that lets the server dedup without reading.

Security rests only on the keys, never on this code being secret (Kerckhoffs) —
which is why it can be public and auditable.
"""

from .blind_index import blind_index, canonicalize, derive_bi_key
from .envelope import (
    RecordContext,
    SealedRecord,
    derive_kek,
    open_record,
    seal,
)
from .primitives import (
    aead_decrypt,
    aead_encrypt,
    ct_equal,
    hkdf_sha256,
    hmac_sha256,
    random_bytes,
)
from .recovery import (
    MalformedRecoveryCode,
    generate_recovery_code,
    user_share_from_recovery_code,
)

__all__ = [
    "RecordContext",
    "SealedRecord",
    "seal",
    "open_record",
    "derive_kek",
    "blind_index",
    "derive_bi_key",
    "canonicalize",
    "generate_recovery_code",
    "user_share_from_recovery_code",
    "MalformedRecoveryCode",
    "aead_encrypt",
    "aead_decrypt",
    "hkdf_sha256",
    "hmac_sha256",
    "ct_equal",
    "random_bytes",
]
