"""End-to-end tests of modules.reports.router — a real HTTP request
through a throwaway FastAPI() + include_router(), the same pattern
test_json.py established for an unmounted route, proving the whole
chain (query params -> service -> repository -> real Postgres -> JSON
response) works together, including that Decimal values round-trip as
strings over real HTTP (Phase 1.3's json.py) with zero extra wiring in
this module — see router.py's own docstring for why.

`get_connection` is overridden to hand back this test's own rolled-back
transaction (`conn`, from ../../conftest.py) instead of opening a real
one against `db.get_engine()` — same technique any FastAPI app uses to
substitute a test double for a request-scoped dependency."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.reports.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    return TestClient(app)


def test_trial_balance_endpoint_returns_decimal_as_string(book, conn):
    resp = client_for(conn).get("/reports/trial-balance", params={"as_of": "2026-02-28", "raw": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_debits"] == "3000.00"
    assert body["in_balance"] is True


def test_balance_sheet_endpoint(book, conn):
    resp = client_for(conn).get("/reports/balance-sheet", params={"as_of": "2026-02-28"})
    assert resp.status_code == 200
    assert resp.json()["total_assets"] == "2200.00"


def test_income_statement_endpoint_includes_prev_next_navigation(book, conn):
    resp = client_for(conn).get("/reports/income-statement",
                                 params={"date_from": "2026-02-01", "date_to": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["net_income"] == "1200.00"
    # shift_range on a 28-day February range: previous period is the same
    # length immediately before it.
    assert body["prev_to"] == "2026-01-31"


def test_income_statement_endpoint_split_returns_a_matrix(book, conn):
    resp = client_for(conn).get("/reports/income-statement",
                                 params={"date_from": "2026-01-01", "date_to": "2026-02-28", "split": "monthly"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["periods"]) == 4  # Jan, Feb, Total, Average
    assert body["periods"][0]["label"] == "2026-01"


def test_cash_flow_endpoint_ties_out(book, conn):
    resp = client_for(conn).get("/reports/cash-flow", params={"date_from": "2026-01-01", "date_to": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["net_change"] == "2200.00"
    assert body["tie_out"]["ok"] is True


def test_variance_endpoint_defaults_to_native_depth(book, conn):
    resp = client_for(conn).get("/reports/variance", params={"as_of": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rolled_up"] is False
    assert body["total_baseline"] == "0.00"
