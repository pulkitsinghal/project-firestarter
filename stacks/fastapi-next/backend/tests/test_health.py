"""Smoke tests for the {{ project_name }} backend skeleton.

Run in the `tools` container: `make backend-test`. Add real domain tests as the
engine layer grows (e.g. asserting invariants hold and stay deterministic).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
