"""End-to-end tests of modules.budget.router — real HTTP requests through
a throwaway FastAPI() + include_router(), the same pattern
modules/reports/test_router.py established, proving the whole chain
(query params/body -> service -> repository -> real Postgres -> JSON
response) works together, including that a guard-trigger SQLAlchemyError
comes back as a 400 with the trigger's own message, not a bare 500."""
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.budget.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # Every route here requires a session
    # (`APIRouter(dependencies=[Depends(get_current_session)])`), and every
    # write route additionally requires `require_csrf_header` — override both
    # to a fixed fake session rather than simulate a real login/CSRF-token
    # round-trip in every test below.
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
    app.dependency_overrides[require_csrf_header] = lambda: {"user_id": 1, "username": "test"}
    return TestClient(app)


def test_budget_grid_endpoint_returns_decimal_totals_as_strings(book, conn):
    resp = client_for(conn).get("/budget", params={"scenario": "BUD", "month": "2026-08"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-08-01"
    rent = next(r for g in body["grouped"] for r in g["rows"] if r["account_code"] == "5100")
    assert rent["budgeted"] == "600.00"
    assert rent["variance"] == "-150.00"


def test_budget_grid_endpoint_normalizes_a_bad_month_to_today(book, conn):
    resp = client_for(conn).get("/budget", params={"scenario": "BUD", "month": "2026-13"})
    assert resp.status_code == 200
    assert resp.json()["month"] == date.today().replace(day=1).isoformat()


def test_budget_grid_endpoint_includes_month_navigation(book, conn):
    resp = client_for(conn).get("/budget", params={"scenario": "BUD", "month": "2026-08"})
    body = resp.json()
    assert body["prev_month"] == "2026-07-01"
    assert body["next_month"] == "2026-09-01"
    assert "2026-08" in body["month_options"]


def test_budget_grid_endpoint_defaults_to_the_zero_stub_with_no_scenario(book, conn):
    resp = client_for(conn).get("/budget", params={"month": "2026-08"})
    assert resp.status_code == 200
    assert resp.json()["grouped"] == []


def test_save_cell_endpoint_upserts(book, conn):
    client = client_for(conn)
    body = {"scenario_id": book["bud"]["id"], "account": "5100",
            "period_month": "2026-09-01", "amount": "150"}
    r1 = client.post("/budget/cell", json=body)
    assert r1.status_code == 200 and r1.json()["amount"] == "150.00"
    r2 = client.post("/budget/cell", json={**body, "amount": "175.50"})
    assert r2.status_code == 200 and r2.json()["amount"] == "175.50"
    grid = client.get("/budget", params={"scenario": "BUD", "month": "2026-09"}).json()
    rent = next(r for g in grid["grouped"] for r in g["rows"] if r["account_code"] == "5100")
    assert rent["budgeted"] == "175.50"


def test_save_cell_endpoint_rejects_an_unknown_account(book, conn):
    resp = client_for(conn).post("/budget/cell", json={
        "scenario_id": book["bud"]["id"], "account": "NOPE999",
        "period_month": "2026-08-01", "amount": "10"})
    assert resp.status_code == 400
    assert "Unknown account code" in resp.json()["detail"]


def test_save_cell_endpoint_rejects_a_full_scenario(book, conn):
    resp = client_for(conn).post("/budget/cell", json={
        "scenario_id": book["actual"]["id"], "account": "5100",
        "period_month": "2026-08-01", "amount": "10"})
    assert resp.status_code == 400
    assert "not income-statement-only" in resp.json()["detail"]
