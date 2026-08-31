"""Phase 0 smoke test: proves the app boots and CI can run pytest at all.

Not a port of any existing test — there is no legacy equivalent. Superseded
by real module tests starting Phase 1, but kept as the one thing that
exercises the full pipeline (install -> import -> TestClient -> assert)
before any product code exists.
"""
from fastapi.testclient import TestClient

from postwarden.main import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
