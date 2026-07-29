"""Synthetic-only local service supervisor contracts."""

from .supervisor import (
    Lease,
    Manifest,
    ManifestError,
    RefusalError,
    ServiceSupervisor,
    ServiceState,
    SyntheticAdapter,
    WakeError,
)

__all__ = [
    "Lease",
    "Manifest",
    "ManifestError",
    "RefusalError",
    "ServiceSupervisor",
    "ServiceState",
    "SyntheticAdapter",
    "WakeError",
]
