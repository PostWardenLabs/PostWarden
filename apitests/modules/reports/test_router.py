"""End-to-end tests of modules.reports.router — a real HTTP request
through a throwaway FastAPI() + include_router(), the same pattern
test_json.py established for an unmounted route, proving the whole
chain (query params -> service -> repository -> real Postgres -> JSON
response) works together, including that Decimal values round-trip as
strings over real HTTP (json.py's own custom encoder) with zero extra
wiring in this module — see router.py's own docstring for why.

`get_connection` is overridden to hand back this test's own rolled-back
transaction (`conn`, from ../../conftest.py) instead of opening a real
one against `db.get_engine()` — same technique any FastAPI app uses to
substitute a test double for a request-scoped dependency."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session
from postwarden.modules.reports.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # Every route here requires a session
    # (`APIRouter(dependencies=[Depends(get_current_session)])`) — no
    # write routes in this module, so there's no `require_csrf_header`
    # to override alongside it.
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
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


# ---------------------------------------------------------------------------
# Exports — one status/content-type/filename smoke test per CSV+XLSX
# pair; `test_export.py` already covers each one's actual row/formula
# content against `export.py` directly, so these only prove the router
# wiring (query params -> service -> export -> Response) holds end to
# end over real HTTP.
# ---------------------------------------------------------------------------


def test_trial_balance_csv_and_xlsx_endpoints(book, conn):
    csv_resp = client_for(conn).get("/reports/trial-balance.csv", params={"as_of": "2026-02-28", "raw": 1})
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"] == "text/csv; charset=utf-8"

    xlsx_resp = client_for(conn).get("/reports/trial-balance.xlsx", params={"as_of": "2026-02-28", "raw": 1})
    assert xlsx_resp.status_code == 200
    assert xlsx_resp.headers["content-type"] == \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_balance_sheet_csv_and_xlsx_endpoints(book, conn):
    assert client_for(conn).get("/reports/balance-sheet.csv", params={"as_of": "2026-02-28"}).status_code == 200
    assert client_for(conn).get("/reports/balance-sheet.xlsx", params={"as_of": "2026-02-28"}).status_code == 200


def test_income_statement_csv_and_xlsx_endpoints_default_to_an_unbounded_range(book, conn):
    """No date_from/date_to at all — unlike `GET /reports/income-
    statement`, the export siblings don't default a blank range to the
    current month (this file's own module docstring), so this also
    proves that difference actually holds over HTTP, not just when
    calling `_income_statement_result` directly."""
    csv_resp = client_for(conn).get("/reports/income-statement.csv")
    assert csv_resp.status_code == 200
    xlsx_resp = client_for(conn).get("/reports/income-statement.xlsx")
    assert xlsx_resp.status_code == 200


def test_cash_flow_csv_and_xlsx_endpoints(book, conn):
    params = {"date_from": "2026-01-01", "date_to": "2026-02-28"}
    assert client_for(conn).get("/reports/cash-flow.csv", params=params).status_code == 200
    assert client_for(conn).get("/reports/cash-flow.xlsx", params=params).status_code == 200


def test_variance_csv_and_xlsx_endpoints(book, conn):
    params = {"as_of": "2026-02-28"}
    assert client_for(conn).get("/reports/variance.csv", params=params).status_code == 200
    assert client_for(conn).get("/reports/variance.xlsx", params=params).status_code == 200


def test_ledger_endpoint(book, conn):
    resp = client_for(conn).get("/reports/ledger", params={"as_of": "2026-02-28", "raw": 1})
    assert resp.status_code == 200
    body = resp.json()
    assets = next(g for g in body["grouped"] if g["label"] == "Assets")
    checking = next(a for a in assets["rows"] if a["code"] == "1100")
    assert checking["total_debit"] == "2200.00"  # Decimal round-trips as a string, same as every other report


def test_ledger_endpoint_has_no_export_siblings(book, conn):
    # Unlike every other report in this module — Ledger has never had
    # CSV/XLSX export siblings.
    assert client_for(conn).get("/reports/ledger.csv").status_code == 404
    assert client_for(conn).get("/reports/ledger.xlsx").status_code == 404
