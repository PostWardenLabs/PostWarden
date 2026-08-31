"""End-to-end tests of modules.staging.router — real HTTP requests
through a throwaway FastAPI() + include_router(), same pattern
modules/entries/test_router.py established."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.staging.router import router

from ...conftest import mk_entry, mk_line, mk_user
from .conftest import mk_schedule


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # Every route here requires a session
    # (`APIRouter(dependencies=[Depends(get_current_session)])`), and every
    # write route additionally requires `require_csrf_header` — override both
    # to a fixed fake session rather than simulate a real login/CSRF-token
    # round-trip in every test below. A *real* `users` row (`mk_user`), not a
    # made-up id: `approve_entries` threads this session's `user_id` into
    # `created_by_user_id`, which has a real FK against `users(id)`.
    session = {"user_id": mk_user(conn)["id"], "username": "test"}
    app.dependency_overrides[get_current_session] = lambda: session
    app.dependency_overrides[require_csrf_header] = lambda: session
    return TestClient(app)


def test_list_pending_returns_the_staged_entry(book, conn, staged_entry):
    resp = client_for(conn).get("/staging")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["id"] == staged_entry
    assert body["entries"][0]["total_debits"] == "500.00"


def test_approve_entries_endpoint(book, conn, staged_entry):
    resp = client_for(conn).post("/staging/approve", json={"entry_ids": [staged_entry]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["approved"]) == 1
    assert body["errors"] == []


def test_approve_entries_endpoint_rejects_an_empty_selection(book, conn):
    resp = client_for(conn).post("/staging/approve", json={"entry_ids": []})
    assert resp.status_code == 400


def test_get_edit_data_endpoint(book, conn, staged_entry):
    resp = client_for(conn).get(f"/staging/{staged_entry}/edit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entry"]["id"] == staged_entry
    assert {l["account_code"] for l in body["lines"]} == {"1100", "4100"}


def test_get_edit_data_endpoint_not_found_returns_400(book, conn):
    resp = client_for(conn).get("/staging/ZZZZZZ/edit")
    assert resp.status_code == 400


def test_save_edit_endpoint(book, conn, staged_entry):
    resp = client_for(conn).post(f"/staging/{staged_entry}/edit", json={
        "description": "Updated", "lines": [
            {"account": "1100", "debit": "200", "credit": ""},
            {"account": "4100", "debit": "", "credit": "200"},
        ],
    })
    assert resp.status_code == 200
    data = client_for(conn).get(f"/staging/{staged_entry}/edit").json()
    assert data["entry"]["description"] == "Updated"


def test_reject_entry_endpoint(book, conn, staged_entry):
    resp = client_for(conn).post(f"/staging/{staged_entry}/reject")
    assert resp.status_code == 200
    assert client_for(conn).get(f"/staging/{staged_entry}/edit").status_code == 400


def test_reject_entry_endpoint_not_found_returns_400(book, conn):
    resp = client_for(conn).post("/staging/ZZZZZZ/reject")
    assert resp.status_code == 400


def test_reject_entries_bulk_endpoint_reports_partial_success(book, conn, staged_entry):
    resp = client_for(conn).post("/staging/reject", json={"entry_ids": ["ZZZZZZ", staged_entry]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rejected"] == [staged_entry]
    assert body["errors"] == ["#ZZZZZZ: not a pending staging entry"]


def test_reject_entries_bulk_endpoint_rejects_an_empty_selection(book, conn):
    resp = client_for(conn).post("/staging/reject", json={"entry_ids": []})
    assert resp.status_code == 400


def test_find_duplicates_endpoint_returns_no_groups_for_a_single_entry(book, conn, staged_entry):
    resp = client_for(conn).get("/staging/duplicates")
    assert resp.status_code == 200
    assert resp.json() == {"groups": []}


def test_merge_duplicates_endpoint(book, conn, staged_entry):
    sched_id = mk_schedule(conn, book["actual"]["id"])
    dup_id = mk_entry(conn, book["staging"]["id"], "2026-03-01", "Dup", scheduled_entry_id=sched_id)
    mk_line(conn, dup_id, book["checking"]["id"], 500, 1)
    mk_line(conn, dup_id, book["salary"]["id"], -500, 2)

    resp = client_for(conn).post("/staging/duplicates/merge", json={
        "keep_id": staged_entry, "remove_ids": [dup_id], "description": "Merged",
    })
    assert resp.status_code == 200
    assert resp.json() == {"kept_entry_id": staged_entry}
    assert client_for(conn).get(f"/staging/{dup_id}/edit").status_code == 400


def test_merge_duplicates_endpoint_rejects_an_empty_selection(book, conn, staged_entry):
    resp = client_for(conn).post("/staging/duplicates/merge", json={
        "keep_id": staged_entry, "remove_ids": [], "description": "x",
    })
    assert resp.status_code == 400
