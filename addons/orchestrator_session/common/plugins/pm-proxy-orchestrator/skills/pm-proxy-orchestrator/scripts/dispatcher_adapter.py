#!/usr/bin/env python3
"""Host-adoption adapter that guards every synthetic root dispatcher call.

This module is an integration primitive, not a global hook.  A host dispatcher
must instantiate ``GuardedDispatcher`` and route every protected tool through
``dispatch``.  Calls made outside that adopted dispatcher cannot be intercepted
by this source-only plugin.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


class DispatcherGuardError(RuntimeError):
    """The guard could not produce a trustworthy decision."""


class GuardedDispatcher:
    """Call the Firestarter root-role guard before any registered tool."""

    def __init__(
        self,
        *,
        guard_script: Path,
        audit_file: Path,
        executors: dict[str, Callable[[Any], Any]],
    ) -> None:
        self.guard_script = guard_script.resolve(strict=True)
        self.audit_file = audit_file.resolve(strict=False)
        self.executors = dict(executors)
        self.underlying_call_count = {name: 0 for name in executors}

    def _evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.guard_script),
                "--state-file",
                str(self.audit_file),
                "--request",
                "-",
                "evaluate",
            ],
            input=json.dumps(request, sort_keys=True, separators=(",", ":")),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DispatcherGuardError("root-role guard returned invalid JSON") from exc
        if completed.returncode != 0 or payload.get("ok") is not True:
            raise DispatcherGuardError("root-role guard failed closed")
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("decision") not in {
            "ALLOW",
            "DENY",
        }:
            raise DispatcherGuardError("root-role guard decision is incompatible")
        return result

    def dispatch(
        self,
        tool_name: str,
        guard_request: dict[str, Any],
        payload: Any = None,
    ) -> dict[str, Any]:
        if tool_name not in self.executors:
            raise DispatcherGuardError("unregistered tool is denied")
        decision = self._evaluate(guard_request)
        if decision["decision"] != "ALLOW":
            return {
                "executed": False,
                "tool_name": tool_name,
                "guard": decision,
            }
        self.underlying_call_count[tool_name] += 1
        return {
            "executed": True,
            "tool_name": tool_name,
            "guard": decision,
            "result": self.executors[tool_name](payload),
        }


class AutoMaterializationAdapter:
    """Apply the canonical-ticket decision before an external task may run."""

    def __init__(
        self,
        *,
        stop: Callable[[str], Any],
        zero_change_handback: Callable[[str], Any],
        archive: Callable[[str], Any],
    ) -> None:
        self.stop = stop
        self.zero_change_handback = zero_change_handback
        self.archive = archive

    def reconcile(
        self,
        *,
        canonical_external_thread_id: str,
        observed_external_thread_id: str,
    ) -> dict[str, Any]:
        if observed_external_thread_id == canonical_external_thread_id:
            return {
                "classification": "CANONICAL_RECEIPT_CONFIRMED",
                "mutation_allowed": True,
                "capacity_eligible": True,
                "actions": [],
            }
        self.stop(observed_external_thread_id)
        self.zero_change_handback(observed_external_thread_id)
        self.archive(observed_external_thread_id)
        return {
            "classification": "DUPLICATE_STOP",
            "mutation_allowed": False,
            "capacity_eligible": False,
            "actions": [
                "STOP_READ_ONLY",
                "RETURN_ZERO_CHANGE_HANDBACK",
                "ARCHIVE_EXTERNAL_MIRROR",
            ],
        }


class OwnerNotificationAdapter:
    """Expose the notification callable only after an exact OWNER_GATE result."""

    def __init__(self, notify: Callable[[Any], Any]) -> None:
        self.notify = notify
        self.call_count = 0

    def deliver(self, classification: dict[str, Any], payload: Any) -> dict[str, Any]:
        if (
            classification.get("classification") != "OWNER_GATE"
            or classification.get("owner_prompt_required") is not True
        ):
            return {
                "delivered": False,
                "reason_code": "OWNER_GATE_REQUIRED",
            }
        self.call_count += 1
        return {
            "delivered": True,
            "reason_code": "OWNER_GATE_CONFIRMED",
            "result": self.notify(payload),
        }
