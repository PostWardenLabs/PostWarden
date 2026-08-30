"""End-to-end test of `dashboard.router` — a real HTTP request through a
throwaway `FastAPI()` + `include_router()`, the same pattern
`analytics/test_router.py` established for an unmounted router.
`get_connection` is overridden to hand back this test's own rolled-back
transaction; `get_current_session` is overridden to a fixed fake
session, since the route requires one."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session
from postwarden.modules.dashboard.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
    return TestClient(app)


def test_get_dashboard_returns_the_summary(book, conn):
    resp = client_for(conn).get("/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["net_worth"] == "6500.00"
    assert body["mtd_income"] == "3000.00"
    assert body["mtd_expenses"] == "1200.00"
    assert len(body["recent"]) == 4
    assert body["upcoming"] == []
