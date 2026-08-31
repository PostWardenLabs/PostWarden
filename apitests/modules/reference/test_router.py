"""End-to-end tests of modules.reference.router — real HTTP requests
through a throwaway FastAPI() + include_router(), same pattern
modules/budget/test_router.py established."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.reference.router import router


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


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def test_list_accounts_endpoint(book, conn):
    resp = client_for(conn).get("/accounts")
    assert resp.status_code == 200
    assert {a["code"] for a in resp.json()} == {"1000", "1100", "4000", "4100"}


def test_create_account_endpoint(book, conn):
    resp = client_for(conn).post("/accounts", json={
        "code": "1200", "name": "Savings", "account_type": "asset",
        "parent_id": book["assets"]["id"], "is_postable": True})
    assert resp.status_code == 201
    assert resp.json()["code"] == "1200"


def test_create_account_endpoint_rejects_an_invalid_type(book, conn):
    resp = client_for(conn).post("/accounts", json={
        "code": "1200", "name": "Savings", "account_type": "not-a-type"})
    assert resp.status_code == 422


def test_quick_create_account_endpoint_generates_a_code(book, conn):
    resp = client_for(conn).post("/accounts/quick-create", json={
        "name": "Savings", "parent_id": book["assets"]["id"]})
    assert resp.status_code == 201
    assert resp.json()["code"].startswith("1")


def test_toggle_account_active_endpoint_400s_for_an_unknown_id(book, conn):
    resp = client_for(conn).post("/accounts/999999/toggle-active")
    assert resp.status_code == 400


def test_toggle_account_cashflow_endpoint(book, conn):
    resp = client_for(conn).post(f"/accounts/{book['checking']['id']}/toggle-cashflow")
    assert resp.status_code == 200
    assert resp.json()["is_cashflow"] is False


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

def test_list_account_levels_endpoint(book, conn):
    resp = client_for(conn).get("/account-levels")
    assert resp.status_code == 200
    assert any(r["id"] == book["level"]["id"] for r in resp.json())


def test_create_account_level_endpoint(book, conn):
    resp = client_for(conn).post("/account-levels", json={"name": "Subaccounts", "depth": 2})
    assert resp.status_code == 201


def test_rename_account_level_endpoint_400s_for_an_unknown_id(book, conn):
    resp = client_for(conn).post("/account-levels/999999/rename", json={"name": "X"})
    assert resp.status_code == 400


def test_delete_account_level_endpoint(book, conn):
    resp = client_for(conn).post(f"/account-levels/{book['level']['id']}/delete")
    assert resp.status_code == 200
    resp2 = client_for(conn).post(f"/account-levels/{book['level']['id']}/delete")
    assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_list_scenarios_endpoint(book, conn):
    resp = client_for(conn).get("/scenarios")
    assert resp.status_code == 200
    assert any(r["id"] == book["actual"]["id"] for r in resp.json())


def test_create_scenario_endpoint(book, conn):
    resp = client_for(conn).post("/scenarios", json={
        "code": "bud", "name": "Budget", "scenario_type": "budget",
        "enforce_balance": False, "income_statement_only": True})
    assert resp.status_code == 201
    assert resp.json()["code"] == "BUD"


def test_create_scenario_endpoint_surfaces_a_trigger_violation(book, conn):
    resp = client_for(conn).post("/scenarios", json={
        "code": "ACTUAL2", "name": "Actual 2", "scenario_type": "actual",
        "enforce_balance": False})
    assert resp.status_code == 400


def test_toggle_scenario_lock_endpoint(book, conn):
    resp = client_for(conn).post(f"/scenarios/{book['actual']['id']}/toggle-lock")
    assert resp.status_code == 200
    assert resp.json()["is_locked"] is True


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

def test_list_payees_endpoint(book, conn):
    resp = client_for(conn).get("/payees")
    assert resp.status_code == 200
    assert any(r["id"] == book["acme"]["id"] for r in resp.json())


def test_create_payee_endpoint_requires_a_name(book, conn):
    resp = client_for(conn).post("/payees", json={"name": "  "})
    assert resp.status_code == 400


def test_quick_create_payee_endpoint(book, conn):
    resp = client_for(conn).post("/payees/quick-create", json={"name": "New Payee"})
    assert resp.status_code == 201


def test_rename_payee_endpoint(book, conn):
    resp = client_for(conn).post(f"/payees/{book['acme']['id']}/rename", json={"name": "Acme Corp"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme Corp"


def test_rename_payee_endpoint_400s_for_an_unknown_id(book, conn):
    resp = client_for(conn).post("/payees/999999/rename", json={"name": "X"})
    assert resp.status_code == 400


def test_delete_payee_endpoint(book, conn):
    resp = client_for(conn).post(f"/payees/{book['other']['id']}/delete")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Other Co"


def test_merge_payees_endpoint(book, conn):
    resp = client_for(conn).post("/payees/merge", json={
        "payee_ids": [book["acme"]["id"], book["other"]["id"]], "target_name": "Merged Co"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["merged"] == 2
    assert body["entries_affected"] == 1


def test_merge_payees_endpoint_400s_with_one_id(book, conn):
    resp = client_for(conn).post("/payees/merge", json={
        "payee_ids": [book["acme"]["id"]], "target_name": "X"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def test_list_tags_endpoint(book, conn):
    resp = client_for(conn).get("/tags")
    assert resp.status_code == 200
    assert any(r["id"] == book["food"]["id"] for r in resp.json())


def test_create_tag_endpoint(book, conn):
    resp = client_for(conn).post("/tags", json={"name": "groceries"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "groceries"


def test_create_tag_endpoint_rejects_more_than_one_name(book, conn):
    resp = client_for(conn).post("/tags", json={"name": "a, b"})
    assert resp.status_code == 400


def test_toggle_tag_active_endpoint(book, conn):
    resp = client_for(conn).post(f"/tags/{book['food']['id']}/toggle-active")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_delete_tag_endpoint(book, conn):
    resp = client_for(conn).post(f"/tags/{book['urgent']['id']}/delete")
    assert resp.status_code == 200
    assert resp.json()["name"] == "urgent"


def test_merge_tags_endpoint(book, conn):
    resp = client_for(conn).post("/tags/merge", json={
        "tag_ids": [book["food"]["id"], book["urgent"]["id"]], "target_name": "merged-tag"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["merged"] == 2
    assert body["entries_affected"] == 1
