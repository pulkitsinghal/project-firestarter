"""Synthetic visible-task tool with deterministic idempotency and crash points."""

from __future__ import annotations

import hashlib


class SyntheticTaskTool:
    def __init__(self, crash: str | None = None):
        self.crash = crash
        self.calls: list[dict[str, str]] = []
        self.created: dict[str, str] = {}
        self.mirrors: dict[str, dict[str, object]] = {}

    def create(self, *, prompt: str, idempotency_key: str) -> str:
        self.calls.append({"prompt": prompt, "idempotency_key": idempotency_key})
        if self.crash == "before-create":
            raise RuntimeError("synthetic crash before create")
        external_id = self.created.setdefault(
            idempotency_key,
            "thread-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:12],
        )
        if self.crash == "after-create":
            raise RuntimeError("synthetic crash after create")
        return external_id

    def surface_mirror(self, *, external_id: str, prompt: str) -> str:
        self.mirrors[external_id] = {
            "prompt": prompt,
            "state": "visible",
            "changes": 0,
        }
        return external_id

    def stop_zero_change_archive(
        self, *, external_id: str, required_actions: list[str]
    ) -> None:
        expected = [
            "STOP_READ_ONLY",
            "RETURN_ZERO_CHANGE_HANDBACK",
            "ARCHIVE_EXTERNAL_MIRROR",
        ]
        if required_actions != expected:
            raise ValueError("mirror stop actions are incomplete")
        mirror = self.mirrors[external_id]
        if mirror["changes"] != 0:
            raise ValueError("mirror mutated before stop")
        mirror["state"] = "archived"
