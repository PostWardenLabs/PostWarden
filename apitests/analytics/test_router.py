"""End-to-end tests of `analytics.router` — a real HTTP request through a
throwaway `FastAPI()` + `include_router()`, the same pattern
`modules/reports/test_router.py` established for an unmounted router.
`get_connection` is overridden to hand back this test's own rolled-back
transaction; `get_settings` is overridden for the Connect BI routes so
the port shown is deterministic regardless of the ambient environment;
`get_current_session` is overridden to a fixed fake session, since every
route here requires one as of Phase 1.14."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.analytics.router import router
from postwarden.config import Settings, get_settings
from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session


def client_for(conn, *, bi_port: str = "5432") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    app.dependency_overrides[get_settings] = lambda: Settings(POSTWARDEN_BI_PORT=bi_port)
    # As of Phase 1.14, every route here (both /api/* and /settings/connect-bi*)
    # requires a session — the same router-level `get_current_session` dependency
    # every other module's own router carries.
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
    return TestClient(app)


def test_api_trial_balance_returns_a_list_of_rows(book, conn):
    resp = client_for(conn).get("/api/trial-balance", params={"as_of": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    by_code = {r["account_code"]: r for r in body}
    assert by_code["1100"]["net"] == "2200.00"


def test_api_accounts_includes_inactive_accounts(book, conn):
    resp = client_for(conn).get("/api/accounts")
    assert resp.status_code == 200
    codes = {r["code"] for r in resp.json()}
    assert "5900" in codes


def test_api_scenarios_returns_entry_counts(book, conn):
    resp = client_for(conn).get("/api/scenarios")
    assert resp.status_code == 200
    by_code = {r["code"]: r for r in resp.json()}
    assert by_code["ACTUAL"]["entry_count"] == 3


def test_api_entries_filters_by_scenario_and_date(book, conn):
    resp = client_for(conn).get("/api/entries", params={
        "scenario": "ACTUAL", "date_from": "2026-02-01", "date_to": "2026-02-28",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 4  # two entries, two lines each
    assert all(r["scenario_code"] == "ACTUAL" for r in body)


def test_api_monthly_activity_unfiltered(book, conn):
    resp = client_for(conn).get("/api/monthly-activity")
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_connect_bi_page_reflects_overridden_settings(book, conn):
    resp = client_for(conn, bi_port="6543").get("/settings/connect-bi")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bi_port"] == "6543"
    assert body["bi_db"] == "postwarden"
    assert any(obj[0] == "v_dim_account" for obj in body["bi_objects"])


def test_connect_bi_pbids_download_has_attachment_headers(book, conn):
    resp = client_for(conn, bi_port="6543").get("/settings/connect-bi/download.pbids")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="PostWarden.pbids"'
    doc = resp.json()
    assert doc["connections"][0]["details"]["address"]["server"].endswith(":6543")
