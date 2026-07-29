"""Bounded voice/NLP intent normalization with no target or execution authority."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Optional, Tuple

from ..contracts import EffectClass, require_id


CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


@dataclass(frozen=True, slots=True)
class NormalizedIntent:
    intent_id: str
    effect: EffectClass
    entity_tokens: Tuple[str, ...]
    ambiguous: bool
    provenance: str = "trusted-user-voice"

    def __post_init__(self) -> None:
        require_id(self.intent_id, "intent_id")
        if (
            len(self.entity_tokens) > 16
            or len(set(self.entity_tokens)) != len(self.entity_tokens)
        ):
            raise ValueError("entity tokens must be unique and bounded")
        for token in self.entity_tokens:
            require_id(token, "entity_token")


def normalize_voice_intent(
    utterance: str,
    catalog: Mapping[str, Tuple[str, EffectClass]],
) -> Optional[NormalizedIntent]:
    """Map trusted user speech to a finite intent catalog.

    Catalog values are product-owned `(intent_id, effect)` pairs. The result has
    no selector, DOM node, coordinate, capability, confirmation, or executor.
    """

    cleaned = CONTROL_CHARS.sub(" ", utterance).strip().lower()
    cleaned = re.sub(r"[^a-z0-9 _-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) > 160:
        return None

    matches = [
        (phrase, intent_id, effect)
        for phrase, (intent_id, effect) in catalog.items()
        if re.search(rf"\b{re.escape(phrase.lower())}\b", cleaned)
    ]
    if not matches:
        return None
    intent_ids = {intent_id for _, intent_id, _ in matches}
    effects = {effect for _, _, effect in matches}
    if len(intent_ids) != 1 or len(effects) != 1:
        return NormalizedIntent(
            intent_id="ambiguous-intent",
            effect=EffectClass.OBSERVE,
            entity_tokens=(),
            ambiguous=True,
        )
    _, intent_id, effect = matches[0]
    return NormalizedIntent(
        intent_id=intent_id,
        effect=effect,
        entity_tokens=(),
        ambiguous=False,
    )
