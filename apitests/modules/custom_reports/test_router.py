"""End-to-end tests of `modules.custom_reports.router` — a real HTTP
request through a throwaway `FastAPI()` + `include_router()`, same
pattern as `modules/reports/`'s own `test_router.py`: query params →
service → repository → real Postgres → JSON, Decimals arriving as
strings. The allowlist's own front line lives here too: an
out-of-enum `metric`/`dimension`/`account_type` must 422 at the
signature, before any module code runs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session
from postwarden.modules.custom_reports.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # Read-only module: session required at the router level, no write
    # routes, so no require_csrf_header to override.
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
    return TestClient(app)


def test_defaults_run_and_echo_config(book, conn):
    resp = client_for(conn).get("/reports/custom")
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "net_amount"
    assert body["dimension"] == "month"
    assert body["scenario"] == "ACTUAL"
    assert body["row_count"] == 2
    # Blank range means unbounded — no prev/next navigation fields.
    assert "prev_from" not in body


def test_decimals_arrive_as_strings(book, conn):
    resp = client_for(conn).get("/reports/custom",
                                params={"account_type": "expense", "dimension": "month"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"][0]["value"] == "350.00"
    assert body["total"] == "410.00"


def test_prev_next_navigation_when_range_is_set(book, conn):
    resp = client_for(conn).get("/reports/custom",
                                params={"date_from": "2026-02-01", "date_to": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["prev_to"] == "2026-01-31"


def test_out_of_enum_values_422_before_any_code_runs(book, conn):
    client = client_for(conn)
    assert client.get("/reports/custom", params={"metric": "bogus"}).status_code == 422
    assert client.get("/reports/custom", params={"dimension": "sql injection"}).status_code == 422
    assert client.get("/reports/custom", params={"account_type": "wealth"}).status_code == 422


def test_service_validation_errors_are_400s(book, conn):
    client = client_for(conn)
    resp = client.get("/reports/custom", params={"scenario": "NOPE"})
    assert resp.status_code == 400
    assert "Unknown scenario" in resp.json()["detail"]
    assert client.get("/reports/custom", params={"dimension": "account_level"}).status_code == 400
    assert client.get("/reports/custom", params={"date_from": "junk"}).status_code == 400


def test_account_level_dimension_over_http(book, conn):
    resp = client_for(conn).get("/reports/custom",
                                params={"dimension": "account_level",
                                        "level_id": book["level"]["id"],
                                        "account_type": "expense"})
    assert resp.status_code == 200
    assert resp.json()["rows"] == [
        {"key": book["expenses"]["id"], "label": "5000 Expenses", "value": "410.00"}]


# ---------------------------------------------------------------------------
# Export siblings — status/content-type/filename smoke tests, same
# division as modules/reports/: test_export.py covers row content
# against export.py directly, these prove the router wiring end to end.
# ---------------------------------------------------------------------------


def test_csv_export_sibling(book, conn):
    resp = client_for(conn).get("/reports/custom.csv", params={"account_type": "expense"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "postwarden-custom-net_amount-by-month-ACTUAL.csv" in resp.headers["content-disposition"]
    assert "Total,410.00" in resp.text


def test_xlsx_export_sibling(book, conn):
    resp = client_for(conn).get("/reports/custom.xlsx", params={"account_type": "expense"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert ".xlsx" in resp.headers["content-disposition"]


def test_export_siblings_share_the_read_routes_validation(book, conn):
    assert client_for(conn).get("/reports/custom.csv",
                                params={"scenario": "NOPE"}).status_code == 400
