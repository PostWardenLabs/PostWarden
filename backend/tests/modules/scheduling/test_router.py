"""End-to-end tests of modules.scheduling.router — real HTTP requests
through a throwaway FastAPI() + include_router(), same pattern
modules/entries/test_router.py established: proving request body ->
service -> repository -> real Postgres -> JSON response works together,
including that a bad `interval_unit` is a 422 from Pydantic's own
`Literal` (not a 400 from hand-rolled validation) and that a domain
`ValueError` comes back as a plain-message 400."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.scheduling.router import router


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # As of Phase 1.14, every route here requires a session
    # (`APIRouter(dependencies=[Depends(get_current_session)])`), and every
    # write route additionally requires `require_csrf_header` — override both
    # to a fixed fake session rather than simulate a real login/CSRF-token
    # round-trip in every test below.
    app.dependency_overrides[get_current_session] = lambda: {"user_id": 1, "username": "test"}
    app.dependency_overrides[require_csrf_header] = lambda: {"user_id": 1, "username": "test"}
    return TestClient(app)


def _schedule_body(book, **kw):
    body = {
        "description": "Rent", "target_scenario_id": book["actual"]["id"],
        "interval_unit": "month", "interval_count": 1,
        "lines": [{"account": "1100", "debit": "500", "credit": ""},
                  {"account": "4100", "debit": "", "credit": "500"}],
    }
    body.update(kw)
    return body


def _template_body(book, **kw):
    body = {
        "name": "Rent template", "description": "Rent",
        "lines": [{"account": "1100", "debit": "500", "credit": ""},
                  {"account": "4100", "debit": "", "credit": "500"}],
    }
    body.update(kw)
    return body


def test_create_schedule_returns_201_and_the_new_id(book, conn):
    resp = client_for(conn).post("/scheduled", json=_schedule_body(book))
    assert resp.status_code == 201
    assert isinstance(resp.json()["id"], int)


def test_create_schedule_unbalanced_lines_returns_400(book, conn):
    body = _schedule_body(book, lines=[{"account": "1100", "debit": "100", "credit": ""},
                                        {"account": "4100", "debit": "", "credit": "50"}])
    resp = client_for(conn).post("/scheduled", json=body)
    assert resp.status_code == 400
    assert "must balance" in resp.json()["detail"]


def test_create_schedule_bad_interval_unit_returns_422(book, conn):
    resp = client_for(conn).post("/scheduled", json=_schedule_body(book, interval_unit="fortnight"))
    assert resp.status_code == 422


def test_list_schedules_returns_what_was_created(book, conn):
    client = client_for(conn)
    client.post("/scheduled", json=_schedule_body(book))
    resp = client.get("/scheduled")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["description"] == "Rent"
    assert body[0]["total_amount"] == "500.00"


def test_toggle_schedule_active_endpoint(book, conn):
    client = client_for(conn)
    sched_id = client.post("/scheduled", json=_schedule_body(book)).json()["id"]
    resp = client.post(f"/scheduled/{sched_id}/toggle-active")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_toggle_schedule_active_unknown_id_returns_400(book, conn):
    resp = client_for(conn).post("/scheduled/999999/toggle-active")
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]


def test_create_template_and_list_templates_endpoint(book, conn):
    client = client_for(conn)
    resp = client.post("/templates", json=_template_body(book, tags="rent"))
    assert resp.status_code == 201
    tpl_id = resp.json()["id"]

    resp = client.get("/templates")
    assert resp.status_code == 200
    [tpl] = resp.json()
    assert tpl["id"] == tpl_id
    assert tpl["lines"][0] == {"code": "1100", "debit": "500.00", "credit": None, "memo": None}
    assert tpl["tags"] == ["rent"]


def test_create_template_unknown_account_returns_400(book, conn):
    body = _template_body(book, lines=[{"account": "9999", "debit": "10", "credit": ""},
                                        {"account": "4100", "debit": "", "credit": "10"}])
    resp = client_for(conn).post("/templates", json=body)
    assert resp.status_code == 400
    assert "Unknown account code" in resp.json()["detail"]


def test_delete_template_endpoint(book, conn):
    client = client_for(conn)
    tpl_id = client.post("/templates", json=_template_body(book)).json()["id"]
    resp = client.post(f"/templates/{tpl_id}/delete")
    assert resp.status_code == 200
    assert client.get("/templates").json() == []


def test_delete_template_unknown_id_returns_400(book, conn):
    resp = client_for(conn).post("/templates/999999/delete")
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]
