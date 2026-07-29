from __future__ import annotations

import http.client
import ipaddress
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import unquote, urlsplit

from tools.service_supervisor.supervisor import (
    HEALTH_KEYS,
    SERVICE_KEYS,
    TOP_LEVEL_KEYS,
    Manifest,
    ManifestError,
    RefusalError,
    ServiceSupervisor,
    SyntheticAdapter,
    WakeError,
)


def service(
    service_id: str = "api",
    *,
    port: int = 18882,
    dependencies: list[str] | None = None,
    wake_timeout_ms: int = 500,
    idle_timeout_ms: int = 100,
    drain_grace_ms: int = 25,
    never_stop: bool = False,
    retain: bool = False,
) -> dict:
    return {
        "id": service_id,
        "adapter": "synthetic",
        "upstream": f"http://127.0.0.1:{port}",
        "dependencies": dependencies or [],
        "health": {"path": "/healthz", "interval_ms": 2},
        "wake_timeout_ms": wake_timeout_ms,
        "idle_timeout_ms": idle_timeout_ms,
        "drain_grace_ms": drain_grace_ms,
        "never_stop": never_stop,
        "retain": retain,
    }


def manifest(*services: dict) -> Manifest:
    return Manifest.from_dict({"schema_version": 1, "services": list(services)})


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RecordingAdapter(SyntheticAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.operations: list[tuple[str, str]] = []

    def start(self, spec):
        self.operations.append(("start", spec.service_id))
        super().start(spec)

    def stop(self, spec):
        self.operations.append(("stop", spec.service_id))
        super().stop(spec)


class BlockingFailAdapter(SyntheticAdapter):
    def __init__(self):
        super().__init__()
        self.bad_start_entered = threading.Event()
        self.allow_bad_failure = threading.Event()

    def start(self, spec):
        if spec.service_id == "bad":
            with self._lock:
                self.start_count[spec.service_id] = (
                    self.start_count.get(spec.service_id, 0) + 1
                )
            self.bad_start_entered.set()
            if not self.allow_bad_failure.wait(timeout=1):
                raise WakeError("test synchronization timeout")
            raise WakeError("synthetic blocked failure")
        super().start(spec)


# Test-only data plane. The shipped supervisor module has no listener or proxy.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_REQUEST_STRIP = _HOP_BY_HOP | frozenset(
    {
        "authorization",
        "cookie",
        "expect",
        "host",
        "content-length",
        "proxy-authorization",
    }
)


def _safe_test_target(raw_path: str) -> tuple[str, str] | None:
    if len(raw_path) > 8192:
        return None
    parsed = urlsplit(raw_path)
    parts = parsed.path.split("/")
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or len(parts) < 3
        or parts[1] != "v1"
    ):
        return None
    service_id = parts[2]
    if not service_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
        for character in service_id
    ):
        return None
    tail = "/" + "/".join(parts[3:])
    decoded = unquote(tail)
    if "\x00" in decoded or "\\" in decoded or any(
        part in (".", "..") for part in decoded.split("/")
    ):
        return None
    if parsed.query:
        tail += "?" + parsed.query
    return service_id, tail


def _test_proxy_handler(supervisor: ServiceSupervisor):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            return

        def _json(self, status: int, payload: dict, retry: bool = False) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if retry:
                self.send_header("Retry-After", "1")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_POST(self):
            self.close_connection = True
            self._json(405, {"error": "method-not-allowed"})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def do_GET(self):
            if self.path == "/_supervisor/status":
                self._json(200, supervisor.status())
                return
            self._proxy()

        def do_HEAD(self):
            if self.path == "/_supervisor/status":
                self._json(200, supervisor.status())
                return
            self._proxy()

        def _proxy(self) -> None:
            target = _safe_test_target(self.path)
            if target is None:
                self._json(404, {"error": "route-refused"})
                return
            service_id, upstream_target = target
            try:
                spec = supervisor.manifest.services[service_id]
                lease = supervisor.acquire(service_id)
            except KeyError:
                self._json(404, {"error": "service-refused"})
                return
            except (RefusalError, WakeError):
                self._json(503, {"error": "service-unavailable"}, retry=True)
                return

            upstream = urlsplit(spec.upstream)
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in _REQUEST_STRIP
            }
            connection = http.client.HTTPConnection(
                upstream.hostname, upstream.port, timeout=spec.wake_timeout_ms / 1000
            )
            try:
                connection.request(self.command, upstream_target, headers=headers)
                response = connection.getresponse()
            except (OSError, http.client.HTTPException):
                supervisor.mark_failed(service_id)
                connection.close()
                lease.release()
                self._json(502, {"error": "upstream-unavailable"})
                return

            try:
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in _HOP_BY_HOP:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                if self.command != "HEAD":
                    while chunk := response.read(64 * 1024):
                        self.wfile.write(chunk)
            finally:
                connection.close()
                lease.release()

    return Handler


class _TestProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def service_actions(self):
        self.supervisor.reap_idle()


def create_test_proxy(
    supervisor: ServiceSupervisor, host: str = "127.0.0.1", port: int = 0
) -> ThreadingHTTPServer:
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise RefusalError("test proxy requires loopback")
    except ValueError as exc:
        raise RefusalError("test proxy requires loopback") from exc
    for spec in supervisor.manifest.services.values():
        upstream = urlsplit(spec.upstream)
        if port and host == upstream.hostname and port == upstream.port:
            raise RefusalError("test proxy cannot target itself")
    server = _TestProxyServer((host, port), _test_proxy_handler(supervisor))
    server.supervisor = supervisor
    return server


class ManifestContractTests(unittest.TestCase):
    def test_machine_schema_matches_runtime_exact_key_contract(self) -> None:
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "service-catalog.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(TOP_LEVEL_KEYS, frozenset(schema["properties"]))
        service_schema = schema["$defs"]["service"]
        health_schema = schema["$defs"]["health"]
        self.assertFalse(service_schema["additionalProperties"])
        self.assertFalse(health_schema["additionalProperties"])
        self.assertEqual(SERVICE_KEYS, frozenset(service_schema["properties"]))
        self.assertEqual(HEALTH_KEYS, frozenset(health_schema["properties"]))
        self.assertEqual("synthetic", service_schema["properties"]["adapter"]["const"])

    def test_accepts_only_explicit_synthetic_loopback_services(self) -> None:
        parsed = manifest(service())
        self.assertEqual(("api",), parsed.topological_order)
        self.assertEqual("synthetic", parsed.services["api"].adapter)

    def test_rejects_unknown_adapter_arbitrary_command_and_unknown_keys(self) -> None:
        wrong_adapter = service()
        wrong_adapter["adapter"] = "docker"
        with self.assertRaisesRegex(ManifestError, "must be synthetic"):
            manifest(wrong_adapter)

        command = service()
        command["command"] = "docker compose down"
        with self.assertRaisesRegex(ManifestError, "unsupported keys"):
            manifest(command)

    def test_rejects_external_dns_credentials_queries_and_paths(self) -> None:
        unsafe = [
            "http://0.0.0.0:8000",
            "http://localhost:8000",
            "https://127.0.0.1:8000",
            "http://user:secret@127.0.0.1:8000",
            "http://127.0.0.1:8000/path",
            "http://127.0.0.1:8000?token=x",
        ]
        for target in unsafe:
            entry = service()
            entry["upstream"] = target
            with self.subTest(target=target), self.assertRaises(ManifestError):
                manifest(entry)
        entry = service()
        entry["health"]["path"] = "/healthz?token=forbidden"
        with self.assertRaisesRegex(ManifestError, "health.path"):
            manifest(entry)

    def test_rejects_duplicate_unknown_dependency_and_cycles(self) -> None:
        with self.assertRaisesRegex(ManifestError, "duplicate service id"):
            manifest(service(), service())
        with self.assertRaisesRegex(ManifestError, "duplicates upstream"):
            manifest(service("one"), service("two"))
        first_ipv6 = service("one", port=18881)
        first_ipv6["upstream"] = "http://[::1]:18881"
        second_ipv6 = service("two", port=18882)
        second_ipv6["upstream"] = "http://[0:0:0:0:0:0:0:1]:18881"
        with self.assertRaisesRegex(ManifestError, "duplicates upstream"):
            manifest(first_ipv6, second_ipv6)
        with self.assertRaisesRegex(ManifestError, "unknown dependency"):
            manifest(service(dependencies=["missing"]))
        with self.assertRaisesRegex(ManifestError, "cycle"):
            manifest(
                service("one", port=18881, dependencies=["two"]),
                service("two", port=18882, dependencies=["one"]),
            )

    def test_rejects_unknown_top_level_and_invalid_bounds(self) -> None:
        with self.assertRaises(ManifestError):
            Manifest.from_dict(
                {"schema_version": 1, "services": [service()], "extra": True}
            )
        with self.assertRaises(ManifestError):
            Manifest.from_dict({"schema_version": True, "services": [service()]})
        entry = service()
        entry["wake_timeout_ms"] = 0
        with self.assertRaises(ManifestError):
            manifest(entry)
        for target in ("http://127.0.0.1:0", "http://127.0.0.1:99999"):
            entry = service()
            entry["upstream"] = target
            with self.subTest(target=target), self.assertRaises(ManifestError):
                manifest(entry)

    def test_manifest_path_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "catalog.json"
            real.write_text(
                json.dumps({"schema_version": 1, "services": [service()]}),
                encoding="utf-8",
            )
            link = root / "catalog-link.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(ManifestError, "bounded regular file"):
                Manifest.from_path(link)


class LifecycleContractTests(unittest.TestCase):
    def test_wake_planner_is_deterministic_and_topological(self) -> None:
        supervisor = ServiceSupervisor(
            manifest(
                service("db", port=18881),
                service("api", port=18882, dependencies=["db"]),
            ),
            SyntheticAdapter(),
        )
        first = supervisor.plan_wake("api")
        second = supervisor.plan_wake("api")
        self.assertEqual(first, second)
        self.assertEqual(
            ["db", "api"],
            [step["service_id"] for step in first["steps"]],
        )
        self.assertEqual(
            ["ensure-ready", "ensure-ready"],
            [step["action"] for step in first["steps"]],
        )
        with self.assertRaisesRegex(RefusalError, "unknown service"):
            supervisor.plan_wake("unknown")

    def test_idle_planner_is_reverse_order_and_does_not_mutate(self) -> None:
        clock = FakeClock()
        supervisor = ServiceSupervisor(
            manifest(
                service("db", port=18881, idle_timeout_ms=0),
                service("api", port=18882, dependencies=["db"], idle_timeout_ms=0),
            ),
            SyntheticAdapter(clock=clock),
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        lease = supervisor.acquire("api")
        lease.release()
        before = supervisor.status()
        plan = supervisor.plan_idle()
        self.assertEqual(plan, supervisor.plan_idle())
        self.assertEqual(["api", "db"], [step["service_id"] for step in plan["steps"]])
        self.assertEqual(before, supervisor.status())

    def test_state_machine_wake_lease_drain_and_stop(self) -> None:
        clock = FakeClock()
        adapter = SyntheticAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(service(idle_timeout_ms=100, drain_grace_ms=25)),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual("STOPPED", front.status()["services"][0]["state"])
        lease = front.acquire("api")
        self.assertEqual("READY", front.status()["services"][0]["state"])
        lease.release()
        clock.advance(0.101)
        front.reap_idle()
        self.assertEqual("DRAINING", front.status()["services"][0]["state"])
        clock.advance(0.026)
        front.reap_idle()
        self.assertEqual("STOPPED", front.status()["services"][0]["state"])

        states = [
            event["to_state"] for event in front.telemetry.events()
        ]
        self.assertEqual(
            ["STARTING", "READY", "DRAINING", "STOPPED"],
            states,
        )

    def test_concurrent_first_requests_coalesce_one_start(self) -> None:
        adapter = SyntheticAdapter(ready_delay={"api": 0.05})
        front = ServiceSupervisor(manifest(service(wake_timeout_ms=1000)), adapter)
        barrier = threading.Barrier(101)
        failures: list[Exception] = []

        def request() -> None:
            barrier.wait()
            try:
                with front.acquire("api"):
                    pass
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                failures.append(exc)

        threads = [threading.Thread(target=request) for _ in range(100)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)
        self.assertFalse(failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(1, adapter.start_count["api"])

    def test_concurrent_failed_wake_is_coalesced_without_retry_storm(self) -> None:
        adapter = SyntheticAdapter(fail_health={"api"})
        supervisor = ServiceSupervisor(
            manifest(service(wake_timeout_ms=30)),
            adapter,
        )
        barrier = threading.Barrier(51)
        failures: list[WakeError] = []

        def request() -> None:
            barrier.wait(timeout=2)
            try:
                supervisor.acquire("api")
            except WakeError as exc:
                failures.append(exc)

        threads = [threading.Thread(target=request) for _ in range(50)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(50, len(failures))
        self.assertEqual(1, adapter.start_count["api"])
        self.assertEqual("FAILED", supervisor.status()["services"][0]["state"])

    def test_active_concurrent_leases_win_race_with_idle_reaper(self) -> None:
        adapter = SyntheticAdapter(ready_delay={"api": 0.02})
        supervisor = ServiceSupervisor(
            manifest(service(idle_timeout_ms=0, drain_grace_ms=0)),
            adapter,
        )
        acquired = threading.Barrier(51)
        release = threading.Barrier(51)
        failures: list[Exception] = []

        def request() -> None:
            try:
                lease = supervisor.acquire("api")
                acquired.wait(timeout=2)
                release.wait(timeout=2)
                lease.release()
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                failures.append(exc)

        threads = [threading.Thread(target=request) for _ in range(50)]
        for thread in threads:
            thread.start()
        acquired.wait(timeout=2)
        for _ in range(20):
            supervisor.reap_idle()
        state = supervisor.status()["services"][0]
        self.assertEqual("READY", state["state"])
        self.assertEqual(50, state["active_leases"])
        self.assertNotIn("api", adapter.stop_count)
        release.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
        self.assertFalse(failures)

    def test_dependencies_start_topologically_and_stop_in_reverse(self) -> None:
        clock = FakeClock()
        adapter = RecordingAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(
                service("db", port=18881, idle_timeout_ms=0, drain_grace_ms=0),
                service(
                    "api",
                    port=18882,
                    dependencies=["db"],
                    idle_timeout_ms=0,
                    drain_grace_ms=0,
                ),
            ),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        lease = front.acquire("api")
        self.assertEqual([("start", "db"), ("start", "api")], adapter.operations)
        lease.release()
        front.reap_idle()
        self.assertEqual(
            [
                ("start", "db"),
                ("start", "api"),
                ("stop", "api"),
                ("stop", "db"),
            ],
            adapter.operations,
        )

    def test_dependency_lease_is_shared_until_all_dependents_release(self) -> None:
        clock = FakeClock()
        adapter = SyntheticAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(
                service("db", port=18881, idle_timeout_ms=0, drain_grace_ms=0),
                service("one", port=18882, dependencies=["db"]),
                service("two", port=18883, dependencies=["db"]),
            ),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        first = front.acquire("one")
        second = front.acquire("two")
        first.release()
        front.reap_idle()
        db = next(
            item for item in front.status()["services"] if item["service_id"] == "db"
        )
        self.assertEqual("READY", db["state"])
        self.assertEqual(1, db["active_leases"])
        second.release()
        front.reap_idle()
        self.assertEqual(1, adapter.stop_count["db"])

    def test_new_lease_cancels_drain(self) -> None:
        clock = FakeClock()
        adapter = SyntheticAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(service(idle_timeout_ms=0, drain_grace_ms=100)),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        first = front.acquire("api")
        first.release()
        front.reap_idle()
        self.assertEqual("DRAINING", front.status()["services"][0]["state"])
        second = front.acquire("api")
        self.assertEqual("READY", front.status()["services"][0]["state"])
        self.assertEqual(1, adapter.start_count["api"])
        second.release()

    def test_never_stop_and_retain_pins_block_idle_stop(self) -> None:
        clock = FakeClock()
        adapter = SyntheticAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(
                service(
                    "pinned",
                    port=18881,
                    idle_timeout_ms=0,
                    drain_grace_ms=0,
                    never_stop=True,
                ),
                service(
                    "retained",
                    port=18882,
                    idle_timeout_ms=0,
                    drain_grace_ms=0,
                    retain=True,
                ),
            ),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        for service_id in ("pinned", "retained"):
            lease = front.acquire(service_id)
            lease.release()
        front.reap_idle()
        self.assertEqual(
            {"READY"}, {entry["state"] for entry in front.status()["services"]}
        )
        front.set_retain("retained", False)
        front.reap_idle()
        retained = next(
            item
            for item in front.status()["services"]
            if item["service_id"] == "retained"
        )
        self.assertEqual("STOPPED", retained["state"])

    def test_pinned_service_keeps_dependency_closure_ready(self) -> None:
        clock = FakeClock()
        adapter = SyntheticAdapter(clock=clock)
        front = ServiceSupervisor(
            manifest(
                service("db", port=18881, idle_timeout_ms=0, drain_grace_ms=0),
                service(
                    "api",
                    port=18882,
                    dependencies=["db"],
                    idle_timeout_ms=0,
                    drain_grace_ms=0,
                    retain=True,
                ),
            ),
            adapter,
            clock=clock,
            sleeper=lambda _seconds: None,
        )
        lease = front.acquire("api")
        lease.release()
        front.reap_idle()
        self.assertEqual(
            {"READY"}, {item["state"] for item in front.status()["services"]}
        )

    def test_bounded_health_timeout_cleans_adapter_and_fails(self) -> None:
        adapter = SyntheticAdapter(fail_health={"api"})
        front = ServiceSupervisor(
            manifest(service(wake_timeout_ms=20)),
            adapter,
        )
        started = time.monotonic()
        with self.assertRaises(WakeError):
            front.acquire("api")
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertEqual("FAILED", front.status()["services"][0]["state"])
        self.assertEqual(1, adapter.stop_count["api"])

    def test_dependency_uses_its_shorter_bounded_wake_timeout(self) -> None:
        adapter = SyntheticAdapter(fail_health={"dep"})
        supervisor = ServiceSupervisor(
            manifest(
                service("dep", port=18881, wake_timeout_ms=20),
                service(
                    "api",
                    port=18882,
                    dependencies=["dep"],
                    wake_timeout_ms=500,
                ),
            ),
            adapter,
        )
        started = time.monotonic()
        with self.assertRaises(WakeError):
            supervisor.acquire("api")
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertNotIn("api", adapter.start_count)

    def test_failed_target_rolls_back_new_dependency(self) -> None:
        adapter = SyntheticAdapter(fail_start={"api"})
        front = ServiceSupervisor(
            manifest(
                service("db", port=18881),
                service("api", port=18882, dependencies=["db"]),
            ),
            adapter,
        )
        with self.assertRaises(WakeError):
            front.acquire("api")
        states = {
            item["service_id"]: item["state"] for item in front.status()["services"]
        }
        self.assertEqual({"api": "FAILED", "db": "STOPPED"}, states)
        self.assertEqual(1, adapter.stop_count["db"])

    def test_stale_failure_rollback_does_not_stop_new_shared_dependency_lease(
        self,
    ) -> None:
        adapter = BlockingFailAdapter()
        supervisor = ServiceSupervisor(
            manifest(
                service("dep", port=18881),
                service("bad", port=18882, dependencies=["dep"]),
                service("good", port=18883, dependencies=["dep"]),
            ),
            adapter,
        )
        failure: list[Exception] = []

        def acquire_bad() -> None:
            try:
                supervisor.acquire("bad")
            except WakeError as exc:
                failure.append(exc)

        bad_thread = threading.Thread(target=acquire_bad)
        bad_thread.start()
        self.assertTrue(adapter.bad_start_entered.wait(timeout=1))
        good_lease = supervisor.acquire("good")
        adapter.allow_bad_failure.set()
        bad_thread.join(timeout=1)
        self.assertTrue(failure)
        states = {
            item["service_id"]: item for item in supervisor.status()["services"]
        }
        self.assertEqual("READY", states["dep"]["state"])
        self.assertEqual(1, states["dep"]["active_leases"])
        self.assertEqual("READY", states["good"]["state"])
        good_lease.release()

    def test_shutdown_cleans_all_synthetic_state_even_when_pinned(self) -> None:
        adapter = SyntheticAdapter()
        front = ServiceSupervisor(
            manifest(service(never_stop=True)),
            adapter,
        )
        lease = front.acquire("api")
        front.shutdown()
        lease.release()
        self.assertEqual("STOPPED", front.status()["services"][0]["state"])
        self.assertEqual(1, adapter.stop_count["api"])
        with self.assertRaises(RefusalError):
            front.acquire("api")

    def test_shutdown_racing_inflight_start_converges_to_stopped(self) -> None:
        adapter = SyntheticAdapter(ready_delay={"api": 0.2})
        supervisor = ServiceSupervisor(
            manifest(service(wake_timeout_ms=500)),
            adapter,
        )
        failures: list[Exception] = []

        def acquire() -> None:
            try:
                supervisor.acquire("api")
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)

        thread = threading.Thread(target=acquire)
        thread.start()
        deadline = time.monotonic() + 0.5
        while "api" not in adapter.start_count and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertIn("api", adapter.start_count)
        supervisor.shutdown()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any(isinstance(exc, RefusalError) for exc in failures))
        self.assertEqual("STOPPED", supervisor.status()["services"][0]["state"])

    def test_unknown_metrics_are_null_and_explicitly_unavailable(self) -> None:
        status = ServiceSupervisor(manifest(service()), SyntheticAdapter()).status()
        metrics = status["services"][0]["resource_metrics"]
        self.assertEqual(
            {"value": None, "available": False}, metrics["cpu_percent"]
        )
        self.assertEqual(
            {"value": None, "available": False}, metrics["memory_bytes"]
        )

    def test_telemetry_is_bounded_to_privacy_safe_fields(self) -> None:
        front = ServiceSupervisor(manifest(service()), SyntheticAdapter())
        with front.acquire("api"):
            pass
        events = front.telemetry.events()
        self.assertTrue(events)
        self.assertTrue(
            all(
                set(event)
                == {
                    "schema_version",
                    "service_id",
                    "from_state",
                    "to_state",
                    "reason",
                }
                for event in events
            )
        )
        serialized = json.dumps(events)
        for forbidden in ("Authorization", "Cookie", "query", "body", "http://"):
            self.assertNotIn(forbidden, serialized)


class _BackendHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[tuple[str, str]]] = []

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        type(self).requests.append(("GET", self.path))
        body = b"synthetic-ready"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        type(self).requests.append(("HEAD", self.path))
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        type(self).requests.append(("POST", self.path))
        self.send_response(500)
        self.end_headers()


class ProxyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        _BackendHandler.requests = []
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), _BackendHandler)
        self.backend_thread = threading.Thread(
            target=self.backend.serve_forever, daemon=True
        )
        self.backend_thread.start()
        backend_port = self.backend.server_address[1]
        self.adapter = SyntheticAdapter(ready_delay={"api": 0.02})
        self.front = ServiceSupervisor(
            manifest(service(port=backend_port, wake_timeout_ms=500)), self.adapter
        )
        self.proxy = create_test_proxy(self.front, "127.0.0.1", 0)
        self.proxy_thread = threading.Thread(
            target=self.proxy.serve_forever, daemon=True
        )
        self.proxy_thread.start()

    def tearDown(self) -> None:
        self.proxy.shutdown()
        self.proxy.server_close()
        self.front.shutdown()
        self.backend.shutdown()
        self.backend.server_close()

    def request(self, method: str, path: str, body: bytes | None = None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.proxy.server_address[1], timeout=1
        )
        connection.request(method, path, body=body)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, payload

    def test_first_get_reaches_upstream_only_after_ready(self) -> None:
        started = time.monotonic()
        status, body = self.request("GET", "/v1/api/private?opaque=value")
        self.assertEqual(200, status)
        self.assertEqual(b"synthetic-ready", body)
        self.assertGreaterEqual(time.monotonic() - started, 0.015)
        self.assertEqual([("GET", "/private?opaque=value")], _BackendHandler.requests)
        self.assertEqual(1, self.adapter.start_count["api"])
        self.assertNotIn("opaque", json.dumps(self.front.telemetry.events()))

    def test_head_is_supported_without_response_body(self) -> None:
        status, body = self.request("HEAD", "/v1/api/healthz")
        self.assertEqual(204, status)
        self.assertEqual(b"", body)
        self.assertEqual([("HEAD", "/healthz")], _BackendHandler.requests)

    def test_methods_with_bodies_fail_closed_before_wake(self) -> None:
        status, payload = self.request("POST", "/v1/api/private", b"secret")
        self.assertEqual(405, status)
        self.assertIn(b"method-not-allowed", payload)
        self.assertEqual([], _BackendHandler.requests)
        self.assertNotIn("api", self.adapter.start_count)

    def test_unknown_and_traversal_routes_fail_before_wake(self) -> None:
        self.assertEqual(404, self.request("GET", "/v1/missing/")[0])
        self.assertEqual(404, self.request("GET", "/v1/api/%2e%2e/private")[0])
        self.assertEqual([], _BackendHandler.requests)
        self.assertNotIn("api", self.adapter.start_count)

    def test_status_is_loopback_metadata_with_truthful_unknowns(self) -> None:
        status, payload = self.request("GET", "/_supervisor/status")
        self.assertEqual(200, status)
        decoded = json.loads(payload)
        metrics = decoded["services"][0]["resource_metrics"]
        self.assertIsNone(metrics["cpu_percent"]["value"])
        self.assertFalse(metrics["cpu_percent"]["available"])

    def test_failed_wake_returns_503_and_zero_upstream_bytes(self) -> None:
        self.front.adapter.fail_health.add("api")
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.proxy.server_address[1], timeout=1
        )
        connection.request("GET", "/v1/api/private")
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        self.assertEqual(503, response.status)
        self.assertEqual("1", response.getheader("Retry-After"))
        self.assertIn(b"service-unavailable", payload)
        self.assertEqual([], _BackendHandler.requests)

    def test_server_poll_loop_reaps_idle_service(self) -> None:
        backend_port = self.backend.server_address[1]
        front = ServiceSupervisor(
            manifest(
                service(
                    port=backend_port,
                    idle_timeout_ms=1,
                    drain_grace_ms=0,
                )
            ),
            SyntheticAdapter(),
        )
        proxy = create_test_proxy(front, "127.0.0.1", 0)
        thread = threading.Thread(
            target=lambda: proxy.serve_forever(poll_interval=0.005), daemon=True
        )
        thread.start()
        try:
            with front.acquire("api"):
                pass
            deadline = time.monotonic() + 0.5
            while (
                front.status()["services"][0]["state"] != "STOPPED"
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            self.assertEqual("STOPPED", front.status()["services"][0]["state"])
        finally:
            proxy.shutdown()
            proxy.server_close()
            front.shutdown()


class ListenerAndSourceSafetyTests(unittest.TestCase):
    def test_synthetic_fixture_external_bind_and_self_proxy_are_refused(self) -> None:
        supervisor = ServiceSupervisor(manifest(service(port=18882)), SyntheticAdapter())
        with self.assertRaisesRegex(RefusalError, "loopback"):
            create_test_proxy(supervisor, "0.0.0.0", 17840)
        with self.assertRaisesRegex(RefusalError, "target itself"):
            create_test_proxy(supervisor, "127.0.0.1", 18882)

    def test_runtime_source_has_no_host_executor_or_docker_socket(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "supervisor.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "docker.sock",
            "subprocess.",
            "launchctl ",
            "docker compose",
            "OLLAMA_KEEP_ALIVE",
            "os.system",
            "shell=True",
            "BaseHTTPRequestHandler",
            "ThreadingHTTPServer",
            "serve_forever",
            "create_server",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
