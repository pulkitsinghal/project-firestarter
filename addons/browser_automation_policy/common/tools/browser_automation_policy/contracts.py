"""Closed, content-minimized types shared by policy and observation adapters.

Raw URLs, selectors, page text, form values, cookies, credentials, and private
records are deliberately absent. Browser-local observers translate those
details into policy-owned opaque IDs and finite state before this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import FrozenSet, Optional, Tuple, Union


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_PRECONDITIONS = frozenset(
    {
        "task-bound",
        "document-current",
        "frame-current",
        "origin-allowed",
        "target-unique",
        "target-actionable",
        "payload-bound",
        "focus-current",
        "geometry-current",
        "remote-session-current",
        "confirmation-current",
        "reversal-ready",
    }
)
ALLOWED_POSTCONDITIONS = frozenset(
    {
        "state-observed",
        "navigation-reconciled",
        "draft-reconciled",
        "external-effect-reconciled",
        "destructive-effect-reconciled",
    }
)


def require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identifier")


class AdapterKind(str, Enum):
    SEMANTIC_DOM = "semantic-dom"
    RELATIVE_XY = "relative-xy"
    CITRIX_REMOTE = "citrix-remote"


class ActionKind(str, Enum):
    OBSERVE = "observe"
    FOCUS = "focus"
    ACTIVATE = "activate"
    SET_VALUE = "set-value"
    CLEAR_VALUE = "clear-value"
    SELECT = "select"
    NAVIGATE = "navigate"
    EXTERNAL_SEND = "external-send"
    SUBMIT = "submit"
    DELETE = "delete"
    GRANT_PERMISSION = "grant-permission"
    UPLOAD = "upload"


class EffectClass(str, Enum):
    OBSERVE = "observe"
    NAVIGATE = "navigate"
    EDIT_DRAFT = "edit-draft"
    EXTERNAL_SUBMIT = "external-submit"
    DESTRUCTIVE = "destructive"


class ConfirmationTier(int, Enum):
    NONE = 0
    USER_INTENT = 1
    ACTION_BOUND = 2
    OWNER_EXTERNAL = 3


class Reversibility(str, Enum):
    READ_ONLY = "read-only"
    REVERSIBLE = "reversible"
    COMPENSATING = "compensating"
    IRREVERSIBLE = "irreversible"


class LedgerStatus(str, Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    HANDED_OFF = "handed-off"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class DecisionCode(str, Enum):
    AUTHORIZED_HANDOFF = "authorized-handoff"
    EXECUTOR_NOT_CONFIGURED = "executor-not-configured"
    INTENT_UNSUPPORTED = "intent-unsupported"
    ADAPTER_NOT_ALLOWED = "adapter-not-allowed"
    EFFECT_NOT_ALLOWED = "effect-not-allowed"
    TARGET_NOT_ALLOWED = "target-not-allowed"
    ORIGIN_NOT_ALLOWED = "origin-not-allowed"
    FRAME_NOT_ALLOWED = "frame-not-allowed"
    CROSS_ORIGIN_FRAME_BLOCKED = "cross-origin-frame-blocked"
    STALE_HANDLE = "stale-handle"
    DOCUMENT_CHANGED = "document-changed"
    FRAME_CHANGED = "frame-changed"
    TARGET_NOT_FOUND = "target-not-found"
    TARGET_AMBIGUOUS = "target-ambiguous"
    TARGET_HIDDEN = "target-hidden"
    TARGET_DISABLED = "target-disabled"
    TARGET_UNSTABLE = "target-unstable"
    TARGET_OBSCURED = "target-obscured"
    SHADOW_ROOT_CLOSED = "shadow-root-closed"
    SEMANTIC_REQUIRED = "semantic-required"
    GEOMETRY_NOT_ALLOWED = "geometry-not-allowed"
    GEOMETRY_UNTRAINED = "geometry-untrained"
    GEOMETRY_DRIFT = "geometry-drift"
    REMOTE_SESSION_CHANGED = "remote-session-changed"
    REMOTE_FRAME_STALE = "remote-frame-stale"
    PRECONDITION_FAILED = "precondition-failed"
    POSTCONDITION_REQUIRED = "postcondition-required"
    CONFIRMATION_REQUIRED = "confirmation-required"
    CONFIRMATION_STALE = "confirmation-stale"
    REVERSAL_REQUIRED = "reversal-required"
    ACTION_REPLAYED = "action-replayed"
    IDEMPOTENCY_COLLISION = "idempotency-collision"
    PRIOR_OUTCOME_INDETERMINATE = "prior-outcome-indeterminate"
    PROMPT_INJECTION_REVIEW = "prompt-injection-review"
    PRIVATE_DATA_DISALLOWED = "private-data-disallowed"
    HANDOFF_DENIED = "handoff-denied"


@dataclass(frozen=True, slots=True)
class DocumentBinding:
    tab_id: int
    document_id: str
    frame_ids: Tuple[int, ...]
    origin_ids: Tuple[str, ...]
    frame_document_ids: Tuple[str, ...]
    frame_generations: Tuple[int, ...]
    document_generation: int
    surface_generation: int
    adapter_version: str

    def __post_init__(self) -> None:
        if self.tab_id < 0:
            raise ValueError("tab_id must be non-negative")
        require_id(self.document_id, "document_id")
        require_id(self.adapter_version, "adapter_version")
        if not self.frame_ids or self.frame_ids[0] != 0:
            raise ValueError("frame_ids must start at the top frame")
        if len(self.frame_ids) > 8 or len(set(self.frame_ids)) != len(self.frame_ids):
            raise ValueError("frame chain must be unique and bounded")
        if not (
            len(self.frame_ids)
            == len(self.origin_ids)
            == len(self.frame_document_ids)
            == len(self.frame_generations)
        ):
            raise ValueError("frame identity chains must have equal length")
        if self.frame_document_ids[0] != self.document_id:
            raise ValueError("top frame document must equal document_id")
        if any(frame_id < 0 for frame_id in self.frame_ids):
            raise ValueError("frame IDs must be non-negative")
        for origin_id in self.origin_ids:
            require_id(origin_id, "origin_id")
        for frame_document_id in self.frame_document_ids:
            require_id(frame_document_id, "frame_document_id")
        if any(generation < 0 for generation in self.frame_generations):
            raise ValueError("frame generations must be non-negative")
        if self.document_generation < 0 or self.surface_generation < 0:
            raise ValueError("generations must be non-negative")


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    grant_id: str
    task_id: str
    allowed_origin_ids: FrozenSet[str]
    allowed_frame_origin_chains: Tuple[Tuple[str, ...], ...]
    allowed_adapters: FrozenSet[AdapterKind]
    allowed_effects: FrozenSet[EffectClass]
    allowed_action_targets: FrozenSet[
        Tuple[AdapterKind, ActionKind, EffectClass, str, str]
    ]
    expires_at_tick: int
    allow_geometry_fallback: bool = False

    def __post_init__(self) -> None:
        require_id(self.grant_id, "grant_id")
        require_id(self.task_id, "task_id")
        for origin_id in self.allowed_origin_ids:
            require_id(origin_id, "allowed_origin_id")
        if not self.allowed_origin_ids or len(self.allowed_origin_ids) > 32:
            raise ValueError("origin allowlist must be non-empty and bounded")
        if (
            not self.allowed_frame_origin_chains
            or len(self.allowed_frame_origin_chains) > 32
        ):
            raise ValueError("frame allowlist must be non-empty and bounded")
        for chain in self.allowed_frame_origin_chains:
            if not chain or len(chain) > 8:
                raise ValueError("frame allowlist chain must be non-empty and bounded")
            for origin_id in chain:
                require_id(origin_id, "frame_origin_id")
                if origin_id not in self.allowed_origin_ids:
                    raise ValueError("frame chain origin is outside the origin allowlist")
        if not self.allowed_action_targets or len(self.allowed_action_targets) > 128:
            raise ValueError("action-target allowlist must be non-empty and bounded")
        for adapter, action, effect, target_kind, target_digest in (
            self.allowed_action_targets
        ):
            if (
                not isinstance(adapter, AdapterKind)
                or not isinstance(action, ActionKind)
                or not isinstance(effect, EffectClass)
            ):
                raise ValueError("action-target allowlist must use typed enums")
            if target_kind not in {"semantic", "relative-region", "remote-region"}:
                raise ValueError("action-target allowlist has an unknown target kind")
            if not SAFE_DIGEST.fullmatch(target_digest):
                raise ValueError("allowed target contract must use a sha256 digest")
        if self.expires_at_tick < 0:
            raise ValueError("expires_at_tick must be non-negative")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "grantId": self.grant_id,
            "taskId": self.task_id,
            "allowedOriginIds": sorted(self.allowed_origin_ids),
            "allowedFrameOriginChains": [
                list(chain) for chain in self.allowed_frame_origin_chains
            ],
            "allowedAdapters": sorted(adapter.value for adapter in self.allowed_adapters),
            "allowedEffects": sorted(effect.value for effect in self.allowed_effects),
            "allowedActionTargets": [
                {
                    "adapter": adapter.value,
                    "action": action.value,
                    "effect": effect.value,
                    "targetKind": target_kind,
                    "targetContractDigest": target_digest,
                }
                for adapter, action, effect, target_kind, target_digest in sorted(
                    self.allowed_action_targets,
                    key=lambda item: tuple(
                        part.value if isinstance(part, Enum) else part
                        for part in item
                    ),
                )
            ],
            "allowGeometryFallback": self.allow_geometry_fallback,
            "expiresAtTick": self.expires_at_tick,
        }

    @classmethod
    def from_contract_dict(cls, value: dict) -> "CapabilityGrant":
        expected = {
            "schemaVersion",
            "grantId",
            "taskId",
            "allowedOriginIds",
            "allowedFrameOriginChains",
            "allowedAdapters",
            "allowedEffects",
            "allowedActionTargets",
            "allowGeometryFallback",
            "expiresAtTick",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("capability grant fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported capability grant schema")
        parsed_targets = set()
        for item in value["allowedActionTargets"]:
            target_keys = {
                "adapter",
                "action",
                "effect",
                "targetKind",
                "targetContractDigest",
            }
            if not isinstance(item, dict) or set(item) != target_keys:
                raise ValueError("capability target fields do not match schema 1.0")
            parsed_targets.add(
                (
                    AdapterKind(item["adapter"]),
                    ActionKind(item["action"]),
                    EffectClass(item["effect"]),
                    item["targetKind"],
                    item["targetContractDigest"],
                )
            )
        return cls(
            grant_id=value["grantId"],
            task_id=value["taskId"],
            allowed_origin_ids=frozenset(value["allowedOriginIds"]),
            allowed_frame_origin_chains=tuple(
                tuple(chain) for chain in value["allowedFrameOriginChains"]
            ),
            allowed_adapters=frozenset(
                AdapterKind(adapter) for adapter in value["allowedAdapters"]
            ),
            allowed_effects=frozenset(
                EffectClass(effect) for effect in value["allowedEffects"]
            ),
            allowed_action_targets=frozenset(parsed_targets),
            expires_at_tick=value["expiresAtTick"],
            allow_geometry_fallback=value["allowGeometryFallback"],
        )


@dataclass(frozen=True, slots=True)
class TargetContract:
    contract_id: str
    role: str
    accessible_name_token: str
    container_contract_id: str

    def __post_init__(self) -> None:
        for field, value in (
            ("contract_id", self.contract_id),
            ("role", self.role),
            ("accessible_name_token", self.accessible_name_token),
            ("container_contract_id", self.container_contract_id),
        ):
            require_id(value, field)

    @property
    def kind(self) -> str:
        return "semantic"

    @property
    def target_contract_id(self) -> str:
        return self.contract_id

    def to_contract_dict(self) -> dict:
        return {
            "kind": self.kind,
            "contractId": self.contract_id,
            "role": self.role,
            "accessibleNameToken": self.accessible_name_token,
            "containerContractId": self.container_contract_id,
        }

    @property
    def contract_digest(self) -> str:
        return canonical_digest(self.to_contract_dict())


@dataclass(frozen=True, slots=True)
class RelativeTargetContract:
    contract_id: str
    role: str
    accessible_name_token: str
    container_contract_id: str
    trained_regime_id: str
    x_ratio: float
    y_ratio: float
    width_ratio: float
    height_ratio: float
    viewport_generation: int
    layout_generation: int
    transform_generation: int

    def __post_init__(self) -> None:
        for field, value in (
            ("contract_id", self.contract_id),
            ("role", self.role),
            ("accessible_name_token", self.accessible_name_token),
            ("container_contract_id", self.container_contract_id),
            ("trained_regime_id", self.trained_regime_id),
        ):
            require_id(value, field)
        for value in (self.x_ratio, self.y_ratio, self.width_ratio, self.height_ratio):
            if not 0.0 <= value <= 1.0:
                raise ValueError("relative target ratios must be normalized")
        if self.width_ratio <= 0.0 or self.height_ratio <= 0.0:
            raise ValueError("relative target size must be positive")
        if self.x_ratio + self.width_ratio > 1.0:
            raise ValueError("relative target exceeds the horizontal viewport")
        if self.y_ratio + self.height_ratio > 1.0:
            raise ValueError("relative target exceeds the vertical viewport")
        if min(
            self.viewport_generation,
            self.layout_generation,
            self.transform_generation,
        ) < 0:
            raise ValueError("relative target generations must be non-negative")

    @property
    def kind(self) -> str:
        return "relative-region"

    @property
    def target_contract_id(self) -> str:
        return self.contract_id

    def to_contract_dict(self) -> dict:
        return {
            "kind": self.kind,
            "contractId": self.contract_id,
            "role": self.role,
            "accessibleNameToken": self.accessible_name_token,
            "containerContractId": self.container_contract_id,
            "trainedRegimeId": self.trained_regime_id,
            "xRatio": self.x_ratio,
            "yRatio": self.y_ratio,
            "widthRatio": self.width_ratio,
            "heightRatio": self.height_ratio,
            "viewportGeneration": self.viewport_generation,
            "layoutGeneration": self.layout_generation,
            "transformGeneration": self.transform_generation,
        }

    @property
    def contract_digest(self) -> str:
        return canonical_digest(self.to_contract_dict())


@dataclass(frozen=True, slots=True)
class RemoteTargetContract:
    region_contract_id: str
    local_window_id: str
    remote_session_epoch: str
    control_epoch: str
    trained_region_id: str
    geometry_generation: int

    def __post_init__(self) -> None:
        for field, value in (
            ("region_contract_id", self.region_contract_id),
            ("local_window_id", self.local_window_id),
            ("remote_session_epoch", self.remote_session_epoch),
            ("control_epoch", self.control_epoch),
            ("trained_region_id", self.trained_region_id),
        ):
            require_id(value, field)
        if self.geometry_generation < 0:
            raise ValueError("remote geometry generation must be non-negative")

    @property
    def kind(self) -> str:
        return "remote-region"

    @property
    def target_contract_id(self) -> str:
        return self.region_contract_id

    def to_contract_dict(self) -> dict:
        return {
            "kind": self.kind,
            "regionContractId": self.region_contract_id,
            "localWindowId": self.local_window_id,
            "remoteSessionEpoch": self.remote_session_epoch,
            "controlEpoch": self.control_epoch,
            "trainedRegionId": self.trained_region_id,
            "geometryGeneration": self.geometry_generation,
        }

    @property
    def contract_digest(self) -> str:
        return canonical_digest(self.to_contract_dict())


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GeometryObservation:
    x_ratio: float
    y_ratio: float
    width_ratio: float
    height_ratio: float
    viewport_generation: int
    layout_generation: int
    transform_generation: int
    trained_regime_id: Optional[str]
    hit_contract_id: Optional[str]

    def __post_init__(self) -> None:
        for value in (self.x_ratio, self.y_ratio, self.width_ratio, self.height_ratio):
            if not 0.0 <= value <= 1.0:
                raise ValueError("geometry ratios must be normalized")
        if self.width_ratio <= 0.0 or self.height_ratio <= 0.0:
            raise ValueError("geometry size must be positive")
        if self.x_ratio + self.width_ratio > 1.0:
            raise ValueError("horizontal geometry exceeds the normalized viewport")
        if self.y_ratio + self.height_ratio > 1.0:
            raise ValueError("vertical geometry exceeds the normalized viewport")
        if min(
            self.viewport_generation,
            self.layout_generation,
            self.transform_generation,
        ) < 0:
            raise ValueError("geometry generations must be non-negative")
        if self.trained_regime_id is not None:
            require_id(self.trained_regime_id, "trained_regime_id")
        if self.hit_contract_id is not None:
            require_id(self.hit_contract_id, "hit_contract_id")


@dataclass(frozen=True, slots=True)
class ElementCandidate:
    node_id: str
    contract_id: str
    role: str
    accessible_name_token: str
    container_contract_id: str
    binding: DocumentBinding
    attached: bool = True
    visible: bool = True
    enabled: bool = True
    inert: bool = False
    stable: bool = True
    obscured: bool = False
    semantic_available: bool = True
    shadow_root: str = "none"
    geometry: Optional[GeometryObservation] = None

    def __post_init__(self) -> None:
        for field, value in (
            ("node_id", self.node_id),
            ("contract_id", self.contract_id),
            ("role", self.role),
            ("accessible_name_token", self.accessible_name_token),
            ("container_contract_id", self.container_contract_id),
        ):
            require_id(value, field)
        if self.shadow_root not in {"none", "open", "closed"}:
            raise ValueError("shadow_root must be none, open, or closed")


@dataclass(frozen=True, slots=True)
class SemanticObservation:
    observation_id: str
    binding: DocumentBinding
    candidates: Tuple[ElementCandidate, ...]
    focus_confirmed: bool = True
    prompt_injection_signal_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_id(self.observation_id, "observation_id")
        if len(self.candidates) > 500:
            raise ValueError("candidate count exceeds policy bound")
        if (
            len(self.prompt_injection_signal_ids) > 16
            or len(set(self.prompt_injection_signal_ids))
            != len(self.prompt_injection_signal_ids)
        ):
            raise ValueError("prompt-injection signals must be unique and bounded")
        for signal_id in self.prompt_injection_signal_ids:
            require_id(signal_id, "prompt_injection_signal_id")


@dataclass(frozen=True, slots=True)
class ActionProposal:
    proposal_id: str
    idempotency_key: str
    task_id: str
    action: ActionKind
    effect: EffectClass
    adapter: AdapterKind
    binding: DocumentBinding
    target: Union[TargetContract, RelativeTargetContract, RemoteTargetContract]
    payload_digest: str
    preconditions: FrozenSet[str]
    postconditions: FrozenSet[str]
    reversibility: Reversibility
    reversal_action: Optional[ActionKind]
    reversal_payload_digest: Optional[str]
    expires_at_tick: int

    def __post_init__(self) -> None:
        for field, value in (
            ("proposal_id", self.proposal_id),
            ("idempotency_key", self.idempotency_key),
            ("task_id", self.task_id),
        ):
            require_id(value, field)
        if not SAFE_DIGEST.fullmatch(self.payload_digest):
            raise ValueError("payload_digest must be a sha256 digest")
        if (
            self.reversal_payload_digest is not None
            and not SAFE_DIGEST.fullmatch(self.reversal_payload_digest)
        ):
            raise ValueError("reversal_payload_digest must be a sha256 digest")
        if self.expires_at_tick < 0:
            raise ValueError("expires_at_tick must be non-negative")
        if not self.preconditions.issubset(ALLOWED_PRECONDITIONS):
            raise ValueError("unknown precondition")
        if not self.postconditions.issubset(ALLOWED_POSTCONDITIONS):
            raise ValueError("unknown postcondition")
        if len(self.preconditions) > 16 or len(self.postconditions) > 8:
            raise ValueError("condition set exceeds policy bound")

    @property
    def proposal_digest(self) -> str:
        binding = {
            "tabId": self.binding.tab_id,
            "documentId": self.binding.document_id,
            "frameIds": list(self.binding.frame_ids),
            "originIds": list(self.binding.origin_ids),
            "frameDocumentIds": list(self.binding.frame_document_ids),
            "frameGenerations": list(self.binding.frame_generations),
            "documentGeneration": self.binding.document_generation,
            "surfaceGeneration": self.binding.surface_generation,
            "adapterVersion": self.binding.adapter_version,
        }
        target = self.target.to_contract_dict()
        canonical = {
            "taskId": self.task_id,
            "action": self.action.value,
            "effect": self.effect.value,
            "adapter": self.adapter.value,
            "binding": binding,
            "target": target,
            "payloadDigest": self.payload_digest,
            "preconditions": sorted(self.preconditions),
            "postconditions": sorted(self.postconditions),
            "reversibility": self.reversibility.value,
            "reversalAction": (
                self.reversal_action.value
                if self.reversal_action is not None
                else None
            ),
            "reversalPayloadDigest": self.reversal_payload_digest,
            "expiresAtTick": self.expires_at_tick,
        }
        return canonical_digest(canonical)

    def to_contract_dict(self) -> dict:
        binding = {
            "tabId": self.binding.tab_id,
            "documentId": self.binding.document_id,
            "frameIds": list(self.binding.frame_ids),
            "originIds": list(self.binding.origin_ids),
            "frameDocumentIds": list(self.binding.frame_document_ids),
            "frameGenerations": list(self.binding.frame_generations),
            "documentGeneration": self.binding.document_generation,
            "surfaceGeneration": self.binding.surface_generation,
            "adapterVersion": self.binding.adapter_version,
        }
        target = self.target.to_contract_dict()
        return {
            "schemaVersion": "1.0",
            "proposalId": self.proposal_id,
            "idempotencyKey": self.idempotency_key,
            "taskId": self.task_id,
            "action": self.action.value,
            "effect": self.effect.value,
            "adapter": self.adapter.value,
            "binding": binding,
            "target": target,
            "payloadDigest": self.payload_digest,
            "preconditions": sorted(self.preconditions),
            "postconditions": sorted(self.postconditions),
            "reversibility": self.reversibility.value,
            "reversalAction": (
                self.reversal_action.value
                if self.reversal_action is not None
                else None
            ),
            "reversalPayloadDigest": self.reversal_payload_digest,
            "expiresAtTick": self.expires_at_tick,
            "proposalDigest": self.proposal_digest,
        }

    @classmethod
    def from_contract_dict(cls, value: dict) -> "ActionProposal":
        expected = {
            "schemaVersion",
            "proposalId",
            "idempotencyKey",
            "taskId",
            "action",
            "effect",
            "adapter",
            "binding",
            "target",
            "payloadDigest",
            "preconditions",
            "postconditions",
            "reversibility",
            "reversalAction",
            "reversalPayloadDigest",
            "expiresAtTick",
            "proposalDigest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("action proposal fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported action proposal schema")

        binding_value = value["binding"]
        binding_keys = {
            "tabId",
            "documentId",
            "frameIds",
            "originIds",
            "frameDocumentIds",
            "frameGenerations",
            "documentGeneration",
            "surfaceGeneration",
            "adapterVersion",
        }
        if not isinstance(binding_value, dict) or set(binding_value) != binding_keys:
            raise ValueError("binding fields do not match schema 1.0")
        parsed_binding = DocumentBinding(
            tab_id=binding_value["tabId"],
            document_id=binding_value["documentId"],
            frame_ids=tuple(binding_value["frameIds"]),
            origin_ids=tuple(binding_value["originIds"]),
            frame_document_ids=tuple(binding_value["frameDocumentIds"]),
            frame_generations=tuple(binding_value["frameGenerations"]),
            document_generation=binding_value["documentGeneration"],
            surface_generation=binding_value["surfaceGeneration"],
            adapter_version=binding_value["adapterVersion"],
        )

        target_value = value["target"]
        if not isinstance(target_value, dict):
            raise ValueError("target must be an object")
        if target_value.get("kind") == "semantic":
            target_keys = {
                "kind",
                "contractId",
                "role",
                "accessibleNameToken",
                "containerContractId",
            }
            if set(target_value) != target_keys:
                raise ValueError("semantic target fields do not match schema 1.0")
            parsed_target: Union[
                TargetContract,
                RelativeTargetContract,
                RemoteTargetContract,
            ] = TargetContract(
                contract_id=target_value["contractId"],
                role=target_value["role"],
                accessible_name_token=target_value["accessibleNameToken"],
                container_contract_id=target_value["containerContractId"],
            )
        elif target_value.get("kind") == "relative-region":
            target_keys = {
                "kind",
                "contractId",
                "role",
                "accessibleNameToken",
                "containerContractId",
                "trainedRegimeId",
                "xRatio",
                "yRatio",
                "widthRatio",
                "heightRatio",
                "viewportGeneration",
                "layoutGeneration",
                "transformGeneration",
            }
            if set(target_value) != target_keys:
                raise ValueError("relative target fields do not match schema 1.0")
            parsed_target = RelativeTargetContract(
                contract_id=target_value["contractId"],
                role=target_value["role"],
                accessible_name_token=target_value["accessibleNameToken"],
                container_contract_id=target_value["containerContractId"],
                trained_regime_id=target_value["trainedRegimeId"],
                x_ratio=target_value["xRatio"],
                y_ratio=target_value["yRatio"],
                width_ratio=target_value["widthRatio"],
                height_ratio=target_value["heightRatio"],
                viewport_generation=target_value["viewportGeneration"],
                layout_generation=target_value["layoutGeneration"],
                transform_generation=target_value["transformGeneration"],
            )
        elif target_value.get("kind") == "remote-region":
            target_keys = {
                "kind",
                "regionContractId",
                "localWindowId",
                "remoteSessionEpoch",
                "controlEpoch",
                "trainedRegionId",
                "geometryGeneration",
            }
            if set(target_value) != target_keys:
                raise ValueError("remote target fields do not match schema 1.0")
            parsed_target = RemoteTargetContract(
                region_contract_id=target_value["regionContractId"],
                local_window_id=target_value["localWindowId"],
                remote_session_epoch=target_value["remoteSessionEpoch"],
                control_epoch=target_value["controlEpoch"],
                trained_region_id=target_value["trainedRegionId"],
                geometry_generation=target_value["geometryGeneration"],
            )
        else:
            raise ValueError("unknown target kind")

        reversal_action = value["reversalAction"]
        parsed = cls(
            proposal_id=value["proposalId"],
            idempotency_key=value["idempotencyKey"],
            task_id=value["taskId"],
            action=ActionKind(value["action"]),
            effect=EffectClass(value["effect"]),
            adapter=AdapterKind(value["adapter"]),
            binding=parsed_binding,
            target=parsed_target,
            payload_digest=value["payloadDigest"],
            preconditions=frozenset(value["preconditions"]),
            postconditions=frozenset(value["postconditions"]),
            reversibility=Reversibility(value["reversibility"]),
            reversal_action=(
                ActionKind(reversal_action)
                if reversal_action is not None
                else None
            ),
            reversal_payload_digest=value["reversalPayloadDigest"],
            expires_at_tick=value["expiresAtTick"],
        )
        if value["proposalDigest"] != parsed.proposal_digest:
            raise ValueError("proposalDigest does not match canonical proposal")
        return parsed


@dataclass(frozen=True, slots=True)
class Confirmation:
    confirmation_id: str
    proposal_id: str
    proposal_digest: str
    payload_digest: str
    document_id: str
    document_generation: int
    surface_generation: int
    tier: ConfirmationTier
    expires_at_tick: int

    def __post_init__(self) -> None:
        for field, value in (
            ("confirmation_id", self.confirmation_id),
            ("proposal_id", self.proposal_id),
            ("document_id", self.document_id),
        ):
            require_id(value, field)
        for field, value in (
            ("proposal_digest", self.proposal_digest),
            ("payload_digest", self.payload_digest),
        ):
            if not SAFE_DIGEST.fullmatch(value):
                raise ValueError(f"{field} must be a sha256 digest")
        if (
            self.document_generation < 0
            or self.surface_generation < 0
            or self.expires_at_tick < 0
        ):
            raise ValueError("confirmation generations and expiry must be non-negative")


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    code: DecisionCode
    required_confirmation: ConfirmationTier
    adapter: AdapterKind
    proposal_id: str
    handoff: Optional[dict] = None
