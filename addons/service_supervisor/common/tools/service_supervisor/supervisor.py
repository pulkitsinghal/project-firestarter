"""A fail-closed, synthetic-only local service supervisor.

This first slice deliberately supports only the ``synthetic`` adapter. It
contains no subprocess, Docker, launchd, Ollama, shell-command, socket-file,
listener, or deployable proxy integration. Telemetry records only bounded
state-transition metadata. The HTTP wake-before-forward proof lives only in the
test fixture.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, Self
from urllib.parse import urlsplit

MAX_MANIFEST_BYTES = 256 * 1024
SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
SAFE_HEALTH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{0,255}$")
TOP_LEVEL_KEYS = frozenset({"schema_version", "services"})
SERVICE_KEYS = frozenset(
    {
        "id",
        "adapter",
        "upstream",
        "dependencies",
        "health",
        "wake_timeout_ms",
        "idle_timeout_ms",
        "drain_grace_ms",
        "never_stop",
        "retain",
    }
)
HEALTH_KEYS = frozenset({"path", "interval_ms"})


class ManifestError(ValueError):
    """The allowlist is invalid and the supervisor must refuse to proceed."""


class RefusalError(RuntimeError):
    """A request or operation is outside the explicit allowlist."""


class WakeError(RuntimeError):
    """A bounded wake/readiness attempt failed."""


class ServiceState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    DRAINING = "DRAINING"
    FAILED = "FAILED"


@dataclass(frozen=True)
class HealthSpec:
    path: str
    interval_ms: int


@dataclass(frozen=True)
class ServiceSpec:
    service_id: str
    adapter: str
    upstream: str
    dependencies: tuple[str, ...]
    health: HealthSpec
    wake_timeout_ms: int
    idle_timeout_ms: int
    drain_grace_ms: int
    never_stop: bool
    retain: bool


def _exact_keys(value: dict, allowed: frozenset[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ManifestError(f"{context} has unsupported keys: {', '.join(unknown)}")


def _bounded_int(value: object, context: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{context} must be an integer")
    if not minimum <= value <= maximum:
        raise ManifestError(f"{context} must be between {minimum} and {maximum}")
    return value


def _strict_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestError(f"{context} must be a boolean")
    return value


def _loopback_http_url(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{context} must be a string")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ManifestError(f"{context} must be a valid loopback HTTP URL") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or not hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ManifestError(f"{context} must be an origin-only loopback HTTP URL")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ManifestError(f"{context} must use a loopback IP literal") from exc
    if not address.is_loopback:
        raise ManifestError(f"{context} must use a loopback IP literal")
    canonical_host = f"[{address.compressed}]" if address.version == 6 else str(address)
    return f"http://{canonical_host}:{port}"


class Manifest:
    """Parsed, validated service allowlist with a deterministic DAG order."""

    def __init__(self, services: Iterable[ServiceSpec]):
        self.services = {service.service_id: service for service in services}
        self.topological_order = self._validate_dag()

    @classmethod
    def from_dict(cls, raw: object) -> Manifest:
        if not isinstance(raw, dict):
            raise ManifestError("manifest must be a JSON object")
        _exact_keys(raw, TOP_LEVEL_KEYS, "manifest")
        if (
            isinstance(raw.get("schema_version"), bool)
            or not isinstance(raw.get("schema_version"), int)
            or raw.get("schema_version") != 1
        ):
            raise ManifestError("manifest schema_version must be exactly 1")
        entries = raw.get("services")
        if not isinstance(entries, list) or not entries:
            raise ManifestError("manifest services must be a non-empty list")
        if len(entries) > 256:
            raise ManifestError("manifest services exceeds the 256-service limit")

        parsed: list[ServiceSpec] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            context = f"services[{index}]"
            if not isinstance(entry, dict):
                raise ManifestError(f"{context} must be an object")
            _exact_keys(entry, SERVICE_KEYS, context)
            service_id = entry.get("id")
            if not isinstance(service_id, str) or not SERVICE_ID_RE.fullmatch(service_id):
                raise ManifestError(f"{context}.id is invalid")
            if service_id in seen:
                raise ManifestError(f"duplicate service id: {service_id}")
            seen.add(service_id)
            if entry.get("adapter") != "synthetic":
                raise ManifestError(
                    f"{context}.adapter must be synthetic in this source-only release"
                )
            dependencies = entry.get("dependencies", [])
            if (
                not isinstance(dependencies, list)
                or any(not isinstance(item, str) for item in dependencies)
                or len(set(dependencies)) != len(dependencies)
            ):
                raise ManifestError(f"{context}.dependencies must be unique service ids")
            health = entry.get("health")
            if not isinstance(health, dict):
                raise ManifestError(f"{context}.health must be an object")
            _exact_keys(health, HEALTH_KEYS, f"{context}.health")
            health_path = health.get("path")
            if not isinstance(health_path, str) or not SAFE_HEALTH_RE.fullmatch(health_path):
                raise ManifestError(f"{context}.health.path is invalid")

            parsed.append(
                ServiceSpec(
                    service_id=service_id,
                    adapter="synthetic",
                    upstream=_loopback_http_url(entry.get("upstream"), f"{context}.upstream"),
                    dependencies=tuple(dependencies),
                    health=HealthSpec(
                        path=health_path,
                        interval_ms=_bounded_int(
                            health.get("interval_ms"),
                            f"{context}.health.interval_ms",
                            1,
                            10_000,
                        ),
                    ),
                    wake_timeout_ms=_bounded_int(
                        entry.get("wake_timeout_ms"),
                        f"{context}.wake_timeout_ms",
                        1,
                        300_000,
                    ),
                    idle_timeout_ms=_bounded_int(
                        entry.get("idle_timeout_ms"),
                        f"{context}.idle_timeout_ms",
                        0,
                        86_400_000,
                    ),
                    drain_grace_ms=_bounded_int(
                        entry.get("drain_grace_ms"),
                        f"{context}.drain_grace_ms",
                        0,
                        60_000,
                    ),
                    never_stop=_strict_bool(
                        entry.get("never_stop", False), f"{context}.never_stop"
                    ),
                    retain=_strict_bool(entry.get("retain", False), f"{context}.retain"),
                )
            )
        return cls(parsed)

    @classmethod
    def from_path(cls, path: str | Path) -> Manifest:
        manifest_path = Path(path)
        try:
            stat = manifest_path.stat()
        except OSError as exc:
            raise ManifestError("manifest is not readable") from exc
        if (
            manifest_path.is_symlink()
            or not manifest_path.is_file()
            or stat.st_size > MAX_MANIFEST_BYTES
        ):
            raise ManifestError("manifest must be a bounded regular file")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError("manifest must be valid UTF-8 JSON") from exc
        return cls.from_dict(raw)

    def _validate_dag(self) -> tuple[str, ...]:
        upstreams: dict[str, str] = {}
        for service in self.services.values():
            if service.upstream in upstreams:
                raise ManifestError(
                    f"{service.service_id} duplicates upstream for "
                    f"{upstreams[service.upstream]}"
                )
            upstreams[service.upstream] = service.service_id
            for dependency in service.dependencies:
                if dependency not in self.services:
                    raise ManifestError(
                        f"{service.service_id} has unknown dependency: {dependency}"
                    )
                if dependency == service.service_id:
                    raise ManifestError(f"{service.service_id} cannot depend on itself")

        visiting: set[str] = set()
        visited: set[str] = set()
        order: list[str] = []

        def visit(service_id: str) -> None:
            if service_id in visiting:
                raise ManifestError("dependency graph contains a cycle")
            if service_id in visited:
                return
            visiting.add(service_id)
            for dependency in self.services[service_id].dependencies:
                visit(dependency)
            visiting.remove(service_id)
            visited.add(service_id)
            order.append(service_id)

        for service_id in sorted(self.services):
            visit(service_id)
        return tuple(order)

    def closure(self, service_id: str) -> tuple[str, ...]:
        if service_id not in self.services:
            raise RefusalError("unknown service")
        needed: set[str] = set()

        def collect(current: str) -> None:
            if current in needed:
                return
            for dependency in self.services[current].dependencies:
                collect(dependency)
            needed.add(current)

        collect(service_id)
        return tuple(item for item in self.topological_order if item in needed)


class LifecycleAdapter(Protocol):
    """Typed lifecycle boundary; v0.1 provides only ``SyntheticAdapter``."""

    def start(self, service: ServiceSpec) -> None: ...

    def ready(self, service: ServiceSpec) -> bool: ...

    def stop(self, service: ServiceSpec) -> None: ...


class SyntheticAdapter:
    """Deterministic, in-memory lifecycle adapter; never mutates host state."""

    def __init__(
        self,
        *,
        ready_delay: dict[str, float] | None = None,
        fail_start: set[str] | None = None,
        fail_health: set[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ready_delay = dict(ready_delay or {})
        self.fail_start = set(fail_start or ())
        self.fail_health = set(fail_health or ())
        self.clock = clock
        self._ready_at: dict[str, float] = {}
        self._lock = threading.Lock()
        self.start_count: dict[str, int] = {}
        self.stop_count: dict[str, int] = {}

    def start(self, service: ServiceSpec) -> None:
        with self._lock:
            self.start_count[service.service_id] = (
                self.start_count.get(service.service_id, 0) + 1
            )
            if service.service_id in self.fail_start:
                raise WakeError("synthetic start refused")
            self._ready_at[service.service_id] = self.clock() + self.ready_delay.get(
                service.service_id, 0.0
            )

    def ready(self, service: ServiceSpec) -> bool:
        with self._lock:
            if service.service_id in self.fail_health:
                return False
            ready_at = self._ready_at.get(service.service_id)
            return ready_at is not None and self.clock() >= ready_at

    def stop(self, service: ServiceSpec) -> None:
        with self._lock:
            self.stop_count[service.service_id] = (
                self.stop_count.get(service.service_id, 0) + 1
            )
            self._ready_at.pop(service.service_id, None)


@dataclass
class _Runtime:
    spec: ServiceSpec
    state: ServiceState = ServiceState.STOPPED
    leases: int = 0
    retain: bool = False
    ready_at: float | None = None
    last_release: float | None = None
    drain_deadline: float | None = None
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )


class Telemetry:
    """Bounded, payload-free transition telemetry."""

    def __init__(self, limit: int = 512):
        self._events: deque[dict] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def transition(
        self, service_id: str, old: ServiceState, new: ServiceState, reason: str
    ) -> None:
        event = {
            "schema_version": 1,
            "service_id": service_id,
            "from_state": old.value,
            "to_state": new.value,
            "reason": reason,
        }
        with self._lock:
            self._events.append(event)

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)


class Lease:
    def __init__(
        self, supervisor: ServiceSupervisor, service_ids: tuple[str, ...]
    ):
        self._supervisor = supervisor
        self._service_ids = service_ids
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._supervisor._release(self._service_ids)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


class ServiceSupervisor:
    """Thread-safe catalog planner, state machine, dependency manager, and reaper."""

    def __init__(
        self,
        manifest: Manifest,
        adapter: LifecycleAdapter,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        telemetry: Telemetry | None = None,
    ):
        self.manifest = manifest
        self.adapter = adapter
        self.clock = clock
        self.sleeper = sleeper
        self.telemetry = telemetry or Telemetry()
        self._runtimes = {
            service_id: _Runtime(spec=spec, retain=spec.retain)
            for service_id, spec in manifest.services.items()
        }
        self._shutdown = False

    def _transition(
        self, runtime: _Runtime, state: ServiceState, reason: str
    ) -> None:
        old = runtime.state
        if old == state:
            return
        runtime.state = state
        self.telemetry.transition(runtime.spec.service_id, old, state, reason)
        runtime.condition.notify_all()

    def acquire(self, service_id: str) -> Lease:
        service_ids = self.manifest.closure(service_id)
        target = self.manifest.services[service_id]
        overall_deadline = self.clock() + (target.wake_timeout_ms / 1000)
        acquired: list[str] = []
        started: list[str] = []
        try:
            for current in service_ids:
                service_deadline = min(
                    overall_deadline,
                    self.clock()
                    + (self.manifest.services[current].wake_timeout_ms / 1000),
                )
                if self._ensure_ready(current, service_deadline):
                    started.append(current)
                runtime = self._runtimes[current]
                with runtime.condition:
                    if runtime.state != ServiceState.READY:
                        raise WakeError("service left READY before lease acquisition")
                    runtime.leases += 1
                    runtime.drain_deadline = None
                    acquired.append(current)
            return Lease(self, tuple(acquired))
        except Exception:
            self._release(tuple(acquired))
            self._rollback(started)
            raise

    def _ensure_ready(self, service_id: str, deadline: float) -> bool:
        runtime = self._runtimes[service_id]
        waited_for_peer = False
        with runtime.condition:
            while True:
                if self._shutdown:
                    raise RefusalError("service supervisor is shutting down")
                if runtime.state == ServiceState.READY:
                    return False
                if runtime.state == ServiceState.DRAINING:
                    runtime.drain_deadline = None
                    self._transition(runtime, ServiceState.READY, "drain-cancelled-by-lease")
                    return False
                if runtime.state == ServiceState.STARTING:
                    waited_for_peer = True
                    remaining = deadline - self.clock()
                    if remaining <= 0:
                        raise WakeError("wake timeout while waiting for peer")
                    runtime.condition.wait(timeout=remaining)
                    continue
                if runtime.state == ServiceState.FAILED and waited_for_peer:
                    raise WakeError("coalesced wake failed")
                self._transition(runtime, ServiceState.STARTING, "first-lease")
                break

        try:
            self.adapter.start(runtime.spec)
            interval = runtime.spec.health.interval_ms / 1000
            while True:
                if self._shutdown:
                    raise RefusalError("service supervisor is shutting down")
                if self.adapter.ready(runtime.spec):
                    with runtime.condition:
                        if self._shutdown:
                            raise RefusalError("service supervisor is shutting down")
                        runtime.ready_at = self.clock()
                        runtime.last_release = None
                        self._transition(runtime, ServiceState.READY, "health-ready")
                    return True
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise WakeError("bounded readiness timeout")
                self.sleeper(min(interval, remaining))
        except Exception as exc:
            try:
                self.adapter.stop(runtime.spec)
            finally:
                with runtime.condition:
                    runtime.ready_at = None
                    runtime.drain_deadline = None
                    if self._shutdown:
                        self._transition(
                            runtime, ServiceState.STOPPED, "shutdown-wake-cleanup"
                        )
                    else:
                        self._transition(runtime, ServiceState.FAILED, "wake-cleanup")
            if self._shutdown:
                raise RefusalError("service supervisor is shutting down") from exc
            if isinstance(exc, WakeError):
                raise
            if isinstance(exc, RefusalError):
                raise
            raise WakeError("synthetic adapter failed") from exc

    def _release(self, service_ids: tuple[str, ...]) -> None:
        now = self.clock()
        for service_id in reversed(service_ids):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                if runtime.leases <= 0:
                    continue
                runtime.leases -= 1
                if runtime.leases == 0:
                    runtime.last_release = now
                runtime.condition.notify_all()

    def _rollback(self, started: list[str]) -> None:
        for service_id in reversed(started):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                if runtime.leases or runtime.state != ServiceState.READY:
                    continue
                self._transition(runtime, ServiceState.DRAINING, "dependency-rollback")
                self.adapter.stop(runtime.spec)
                runtime.ready_at = None
                runtime.drain_deadline = None
                self._transition(runtime, ServiceState.STOPPED, "dependency-rollback-clean")

    def set_retain(self, service_id: str, retain: bool) -> None:
        if service_id not in self._runtimes or not isinstance(retain, bool):
            raise RefusalError("unknown service or invalid retain pin")
        runtime = self._runtimes[service_id]
        with runtime.condition:
            runtime.retain = retain

    def plan_wake(self, service_id: str) -> dict:
        """Return a deterministic, non-executing wake plan for one allowlisted id."""
        closure = self.manifest.closure(service_id)
        return {
            "schema_version": 1,
            "kind": "wake-plan",
            "target_service_id": service_id,
            "steps": [
                {
                    "sequence": sequence,
                    "action": "ensure-ready",
                    "service_id": current,
                    "adapter": self.manifest.services[current].adapter,
                    "wake_timeout_ms": self.manifest.services[current].wake_timeout_ms,
                }
                for sequence, current in enumerate(closure, start=1)
            ],
        }

    def plan_idle(self, now: float | None = None) -> dict:
        """Return eligible idle transitions without mutating lifecycle state."""
        checked_at = self.clock() if now is None else now
        protected: set[str] = set()
        for service_id, runtime in self._runtimes.items():
            with runtime.condition:
                if runtime.state in (ServiceState.STOPPED, ServiceState.FAILED):
                    continue
                if runtime.spec.never_stop or runtime.retain:
                    protected.update(self.manifest.closure(service_id))

        steps: list[dict] = []
        for service_id in reversed(self.manifest.topological_order):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                if runtime.leases or service_id in protected:
                    continue
                if runtime.state == ServiceState.READY:
                    idle_since = (
                        runtime.last_release
                        if runtime.last_release is not None
                        else runtime.ready_at
                    )
                    if idle_since is None:
                        continue
                    if checked_at - idle_since >= runtime.spec.idle_timeout_ms / 1000:
                        steps.append(
                            {
                                "sequence": len(steps) + 1,
                                "action": "begin-drain",
                                "service_id": service_id,
                                "drain_grace_ms": runtime.spec.drain_grace_ms,
                            }
                        )
                elif (
                    runtime.state == ServiceState.DRAINING
                    and runtime.drain_deadline is not None
                    and checked_at >= runtime.drain_deadline
                ):
                    steps.append(
                        {
                            "sequence": len(steps) + 1,
                            "action": "complete-stop",
                            "service_id": service_id,
                        }
                    )
        return {
            "schema_version": 1,
            "kind": "idle-plan",
            "steps": steps,
        }

    def reap_idle(self) -> None:
        now = self.clock()
        protected: set[str] = set()
        for service_id, runtime in self._runtimes.items():
            with runtime.condition:
                if runtime.state in (ServiceState.STOPPED, ServiceState.FAILED):
                    continue
                if runtime.spec.never_stop or runtime.retain:
                    protected.update(self.manifest.closure(service_id))
        for service_id in reversed(self.manifest.topological_order):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                if runtime.state == ServiceState.READY:
                    if (
                        runtime.leases
                        or runtime.spec.never_stop
                        or runtime.retain
                        or service_id in protected
                    ):
                        continue
                    idle_since = (
                        runtime.last_release
                        if runtime.last_release is not None
                        else runtime.ready_at
                    )
                    if idle_since is None:
                        continue
                    if now - idle_since < runtime.spec.idle_timeout_ms / 1000:
                        continue
                    runtime.drain_deadline = (
                        now + runtime.spec.drain_grace_ms / 1000
                    )
                    self._transition(runtime, ServiceState.DRAINING, "idle-lease-expired")
                if (
                    runtime.state == ServiceState.DRAINING
                    and runtime.leases == 0
                    and runtime.drain_deadline is not None
                    and now >= runtime.drain_deadline
                ):
                    self.adapter.stop(runtime.spec)
                    runtime.ready_at = None
                    runtime.last_release = None
                    runtime.drain_deadline = None
                    self._transition(runtime, ServiceState.STOPPED, "drain-complete")

    def mark_failed(self, service_id: str) -> None:
        if service_id not in self._runtimes:
            raise RefusalError("unknown service")
        runtime = self._runtimes[service_id]
        with runtime.condition:
            self.adapter.stop(runtime.spec)
            runtime.ready_at = None
            runtime.drain_deadline = None
            self._transition(runtime, ServiceState.FAILED, "readiness-lost")

    def status(self) -> dict:
        services = []
        for service_id in sorted(self._runtimes):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                services.append(
                    {
                        "service_id": service_id,
                        "state": runtime.state.value,
                        "active_leases": runtime.leases,
                        "retain": runtime.retain,
                        "never_stop": runtime.spec.never_stop,
                        "resource_metrics": {
                            "cpu_percent": {"value": None, "available": False},
                            "memory_bytes": {"value": None, "available": False},
                        },
                    }
                )
        return {"schema_version": 1, "services": services}

    def shutdown(self) -> None:
        self._shutdown = True
        for service_id in reversed(self.manifest.topological_order):
            runtime = self._runtimes[service_id]
            with runtime.condition:
                if runtime.state != ServiceState.STOPPED:
                    self._transition(runtime, ServiceState.DRAINING, "supervisor-shutdown")
                    self.adapter.stop(runtime.spec)
                    runtime.leases = 0
                    runtime.ready_at = None
                    runtime.last_release = None
                    runtime.drain_deadline = None
                    self._transition(runtime, ServiceState.STOPPED, "shutdown-cleanup")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    plan_wake = subparsers.add_parser("plan-wake")
    plan_wake.add_argument("--manifest", required=True)
    plan_wake.add_argument("--service", required=True)
    args = parser.parse_args(argv)

    try:
        manifest = Manifest.from_path(args.manifest)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "adapter": "synthetic",
                        "services": sorted(manifest.services),
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        supervisor = ServiceSupervisor(manifest, SyntheticAdapter())
        print(
            json.dumps(
                supervisor.plan_wake(args.service),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except (ManifestError, RefusalError) as exc:
        print(f"refused: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
