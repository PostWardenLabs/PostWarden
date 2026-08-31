"""End-to-end tests of modules.imports.router — real HTTP requests
through a throwaway FastAPI() + include_router(), the same pattern
`modules/entries/test_router.py` established. `POST /import` and `POST
/import/mapped/preview` exercise real multipart file uploads (`files=`),
not JSON bodies — the one shape no prior module's own router needed."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.imports.router import router

from ...conftest import mk_user


def client_for(conn) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_connection] = lambda: conn
    # Every route here requires a session
    # (`APIRouter(dependencies=[Depends(get_current_session)])`), and every
    # write route additionally requires `require_csrf_header` — override both
    # to a fixed fake session rather than simulate a real login/CSRF-token
    # round-trip in every test below. A *real* `users` row (`mk_user`), not a
    # made-up id: `import_csv`/`import_mapped_commit` both thread this
    # session's `user_id` into `imported_by_user_id`, which has a real FK
    # against `users(id)`.
    session = {"user_id": mk_user(conn)["id"], "username": "test"}
    app.dependency_overrides[get_current_session] = lambda: session
    app.dependency_overrides[require_csrf_header] = lambda: session
    return TestClient(app)


def _csv(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def test_recent_batches_endpoint_returns_empty_when_nothing_imported_yet(book, conn):
    resp = client_for(conn).get("/import")
    assert resp.status_code == 200
    assert resp.json() == {"recent_batches": []}


def test_import_csv_endpoint_stages_entries(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Imported entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Imported entry,{book['salary']['code']},,40",
    )
    resp = client_for(conn).post(
        "/import", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("bank.csv", content, "text/csv")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_count"] == 1
    assert body["errors"] == []

    listed = client_for(conn).get("/import").json()["recent_batches"]
    assert listed[0]["id"] == body["batch_id"]
    assert listed[0]["filename"] == "bank.csv"


def test_import_csv_endpoint_rejects_a_file_missing_required_columns(book, conn):
    resp = client_for(conn).post(
        "/import", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("bad.csv", "Date,Description\n2026-08-01,Nope\n", "text/csv")})
    assert resp.status_code == 400
    assert "Missing required column" in resp.json()["detail"]


def test_import_mapped_preview_endpoint_returns_pickers_and_the_roundtrip_content(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    resp = client_for(conn).post(
        "/import/mapped/preview", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 1
    assert body["accounts_found"] == ["Checking"]
    assert body["categories_found"] == ["Rent"]
    assert body["target_scenario_id"] == book["actual"]["id"]
    assert body["filename"] == "export.csv"
    assert "file_content_b64" in body


def test_import_mapped_preview_endpoint_rejects_a_bad_file(book, conn):
    resp = client_for(conn).post(
        "/import/mapped/preview", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("bad.csv", "Date,Amount\n2026-08-01,10\n", "text/csv")})
    assert resp.status_code == 400


def test_import_mapped_commit_endpoint_stages_from_a_preview_response(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    preview = c.post(
        "/import/mapped/preview", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped", json={
        "filename": preview["filename"], "target_scenario_id": preview["target_scenario_id"],
        "file_content_b64": preview["file_content_b64"],
        "account_map": {"Checking": book["checking"]["code"]},
        "category_map": {"Rent": book["rent"]["code"]},
        "flip_sign": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_count"] == 1
    assert body["errors"] == []


def test_import_mapped_commit_endpoint_rejects_an_unmapped_account(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    preview = c.post(
        "/import/mapped/preview", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped", json={
        "filename": preview["filename"], "target_scenario_id": preview["target_scenario_id"],
        "file_content_b64": preview["file_content_b64"],
        "account_map": {}, "category_map": {}, "flip_sign": False,
    })
    assert resp.status_code == 400
