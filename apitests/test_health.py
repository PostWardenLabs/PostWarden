"""Smoke test: proves the app boots and CI can run pytest at all.

Superseded in coverage by the real module tests, but kept as the cheapest
possible check that the full pipeline (install -> import -> TestClient ->
assert) still works.
"""
from fastapi.testclient import TestClient

from postwarden.main import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
