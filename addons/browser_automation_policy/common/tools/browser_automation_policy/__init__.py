"""Source-only browser automation policy and semantic adapter contracts."""

from .contracts import (
    ActionKind,
    ActionProposal,
    AdapterKind,
    CapabilityGrant,
    Confirmation,
    ConfirmationTier,
    Decision,
    DecisionCode,
    DocumentBinding,
    EffectClass,
    ElementCandidate,
    GeometryObservation,
    LedgerStatus,
    RelativeTargetContract,
    Reversibility,
    RemoteTargetContract,
    SemanticObservation,
    TargetContract,
)
from .ledger import ActionLedger
from .policy import BrowserAutomationPolicy

__all__ = [
    "ActionKind",
    "ActionLedger",
    "ActionProposal",
    "AdapterKind",
    "BrowserAutomationPolicy",
    "CapabilityGrant",
    "Confirmation",
    "ConfirmationTier",
    "Decision",
    "DecisionCode",
    "DocumentBinding",
    "EffectClass",
    "ElementCandidate",
    "GeometryObservation",
    "LedgerStatus",
    "RelativeTargetContract",
    "Reversibility",
    "RemoteTargetContract",
    "SemanticObservation",
    "TargetContract",
]

__version__ = "0.1.0"
