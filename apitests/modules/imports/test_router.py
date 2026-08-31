"""End-to-end tests of modules.imports.router — real HTTP requests
through a throwaway FastAPI() + include_router(), the same pattern
`modules/entries/test_router.py` established. `POST /import` and `POST
/import/mapped/columns` exercise real multipart file uploads (`files=`),
not JSON bodies — the one shape no prior module's own router needed;
every later mapped-importer step (`/mapped/preview`, `/mapped/validate`,
`/mapped`) is JSON, round-tripping `file_content_b64` (and now `shape`/
`column_map`/`column_kinds`/`value_maps`, IMPORT_WIZARD.md §7 Phase 4)
forward."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from postwarden.db import get_connection
from postwarden.modules.auth.deps import get_current_session, require_csrf_header
from postwarden.modules.imports import service
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


MAPPED_COLUMN_MAP = {"account": "Account", "date": "Date", "payee": "Payee",
                      "memo": "Notes", "category": "Category", "amount": "Amount"}


def test_import_mapped_columns_endpoint_returns_shape_fields_and_the_roundtrip_content(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    resp = client_for(conn).post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["Account", "Date", "Payee", "Notes", "Category", "Amount"]
    assert body["sample_rows"][0]["Account"] == "Checking"
    # IMPORT_WIZARD.md §7 Phase 4 item 1 — a one-row, no repeated-key file
    # sniffs to the "one"/"signed" shape, same shape the old mapped
    # importer always assumed implicitly.
    assert body["shape"] == service.IMPORT_DEFAULT_SHAPE
    fields = body["fields_by_shape"]["one:signed"]
    assert {f["key"] for f in fields} == \
        {"account", "date", "payee", "description", "memo", "category", "amount"}
    assert body["target_scenario_id"] == book["actual"]["id"]
    assert body["filename"] == "export.csv"
    assert "file_content_b64" in body
    # Phase 2 (IMPORT_WIZARD.md §7) — the dialect panel's own guess and
    # its two option lists, sniffed from this same file.
    assert body["dialect"] == {
        "delimiter": ",", "header_row": 0, "decimal_separator": ".",
        "thousands_separator": "", "date_format": "iso",
    }
    assert {d["key"] for d in body["delimiters"]} == {",", ";", "\t", "|"}
    assert {d["key"] for d in body["date_formats"]} == {"iso", "us", "eu"}


def test_import_mapped_columns_endpoint_sniffs_a_semicolon_european_dialect(book, conn):
    content = _csv(
        "Konto;Datum;Betrag",
        "Girokonto;2026-08-01;-500,00",
    )
    resp = client_for(conn).post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")})
    assert resp.status_code == 200
    dialect = resp.json()["dialect"]
    assert dialect["delimiter"] == ";"
    assert dialect["decimal_separator"] == ","


def test_import_mapped_columns_endpoint_sniffs_a_grouped_debit_credit_shape(book, conn):
    # IMPORT_WIZARD.md §7 Phase 4 item 1 — the old plain-importer's own
    # Export-CSV shape, now just another sniff outcome for the one
    # unified columns endpoint.
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Rent,{book['checking']['code']},,40",
        f"1,2026-08-01,Rent,{book['rent']['code']},40,",
    )
    resp = client_for(conn).post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")})
    assert resp.status_code == 200
    shape = resp.json()["shape"]
    assert shape["rows_per_entry"] == "grouped"
    assert shape["amount_style"] == "debit_credit"
    assert shape["group_key_column"] == "Entry #"


def test_import_mapped_columns_reparse_endpoint_re_reads_the_same_file_with_an_overridden_dialect(book, conn):
    # A semicolon file whose delimiter got sniffed as ',' by mistake (or
    # whatever reason a user wants to override it) — the reparse endpoint
    # re-reads the *same already-uploaded* file, not a new upload.
    content = "junk header line\n" + _csv("A;B", "x;y")
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("weird.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/columns/reparse", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"],
        "dialect": {"delimiter": ";", "header_row": 1},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["A", "B"]
    assert body["sample_rows"] == [{"A": "x", "B": "y"}]
    assert body["dialect"] == {**columns["dialect"], "delimiter": ";", "header_row": 1}


def test_import_mapped_columns_reparse_endpoint_rejects_an_empty_file(book, conn):
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", _csv("A,B", "x,y"), "text/csv")}).json()

    # header_row past the end of the (short) file leaves nothing to read.
    resp = c.post("/import/mapped/columns/reparse", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "dialect": {"header_row": 50},
    })
    assert resp.status_code == 400


def test_import_mapped_columns_endpoint_rejects_an_empty_file(book, conn):
    resp = client_for(conn).post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("bad.csv", "", "text/csv")})
    assert resp.status_code == 400


def test_import_mapped_preview_endpoint_returns_pickers_and_the_roundtrip_content(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 1
    assert body["values_found"]["account"] == {"distinct": ["Checking"], "has_blank_rows": False}
    assert body["values_found"]["category"] == {"distinct": ["Rent"], "has_blank_rows": False}
    assert body["target_scenario_id"] == book["actual"]["id"]
    assert body["filename"] == "export.csv"
    assert body["column_map"] == MAPPED_COLUMN_MAP
    assert "file_content_b64" in body


def test_import_mapped_preview_endpoint_omits_a_code_kind_column(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        f"{book['checking']['code']},2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP, "column_kinds": {"account": "code"},
    })
    assert resp.status_code == 200
    assert "account" not in resp.json()["values_found"]
    assert "category" in resp.json()["values_found"]


def test_import_mapped_preview_endpoint_rejects_an_incomplete_column_map(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": {"account": "Account"},
    })
    assert resp.status_code == 400


def test_import_mapped_commit_endpoint_stages_from_a_preview_response(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()
    preview = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP,
    }).json()

    resp = c.post("/import/mapped", json={
        "filename": preview["filename"], "target_scenario_id": preview["target_scenario_id"],
        "file_content_b64": preview["file_content_b64"], "shape": preview["shape"],
        "column_map": preview["column_map"],
        "value_maps": {"account": {"Checking": book["checking"]["code"]},
                        "category": {"Rent": book["rent"]["code"]}},
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
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()
    preview = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP,
    }).json()

    resp = c.post("/import/mapped", json={
        "filename": preview["filename"], "target_scenario_id": preview["target_scenario_id"],
        "file_content_b64": preview["file_content_b64"], "shape": preview["shape"],
        "column_map": preview["column_map"], "value_maps": {"account": {}, "category": {}}, "flip_sign": False,
    })
    assert resp.status_code == 400
    # IMPORT_WIZARD.md §7 Phase 3 item 2 — blocked outright, nothing
    # staged, `skip_bad_rows` left at its default `False`.
    assert c.get("/import").json()["recent_batches"] == []


def test_import_mapped_validate_endpoint_reports_row_errors_without_staging_anything(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/validate", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP, "value_maps": {"account": {}, "category": {}}, "flip_sign": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups_count"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row_no"] == 2
    assert "No mapping chosen for account" in body["errors"][0]["message"]
    assert body["column_map"] == MAPPED_COLUMN_MAP
    assert body["value_maps"] == {"account": {}, "category": {}}
    assert c.get("/import").json()["recent_batches"] == []


def test_import_mapped_validate_endpoint_returns_zero_errors_for_a_clean_file(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/validate", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP,
        "value_maps": {"account": {"Checking": book["checking"]["code"]},
                        "category": {"Rent": book["rent"]["code"]}},
        "flip_sign": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups_count"] == 1
    assert body["errors"] == []


def test_import_mapped_validate_endpoint_resolves_a_code_kind_column_against_the_database(book, conn):
    # IMPORT_WIZARD.md §7 Phase 4 item 2 — the one bulk `known_codes`
    # lookup this route does before calling into `service.validate_file`,
    # restoring a precise per-row "unknown account code" diagnostic.
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "NOTACODE,2026-08-01,Landlord,,Rent,-500",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()

    resp = c.post("/import/mapped/validate", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP, "column_kinds": {"account": "code"},
        "value_maps": {"category": {"Rent": book["rent"]["code"]}}, "flip_sign": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups_count"] == 0
    assert len(body["errors"]) == 1
    assert "Unknown account code 'NOTACODE'" in body["errors"][0]["message"]


def test_import_mapped_commit_endpoint_stages_the_good_rows_when_skip_bad_rows_is_true(book, conn):
    # The end-to-end flow the review step actually follows: validate
    # first (comes back with one row error), then commit with
    # `skip_bad_rows: true` to stage the rest and skip that row.
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
        "Checking,2026-08-02,Employer,,,1000",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()
    # blank-category row 2 is left unmapped on purpose
    value_maps = {"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}}

    validation = c.post("/import/mapped/validate", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": MAPPED_COLUMN_MAP, "value_maps": value_maps, "flip_sign": False,
    }).json()
    assert validation["groups_count"] == 1
    assert len(validation["errors"]) == 1

    resp = c.post("/import/mapped", json={
        "filename": validation["filename"], "target_scenario_id": validation["target_scenario_id"],
        "file_content_b64": validation["file_content_b64"], "shape": validation["shape"],
        "column_map": validation["column_map"], "value_maps": validation["value_maps"],
        "flip_sign": validation["flip_sign"], "skip_bad_rows": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_count"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row_no"] == 3


def test_import_mapped_commit_endpoint_carries_an_edited_dialect_through_preview_and_commit(book, conn):
    # Phase 2 end to end: a semicolon-delimited, comma-decimal file —
    # sniffed correctly here, but exercised via an explicit user-chosen
    # `dialect` the same way an edit in the dialect panel would arrive.
    content = _csv(
        "Konto;Datum;Betrag",
        "Checking;2026-08-01;-500,00",
    )
    dialect = {"delimiter": ";", "decimal_separator": ",", "thousands_separator": "."}
    column_map = {"account": "Konto", "date": "Datum", "amount": "Betrag"}
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()
    assert columns["dialect"]["delimiter"] == ";"  # sniffed correctly, not user-overridden here

    preview = c.post("/import/mapped/preview", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": columns["shape"],
        "column_map": column_map, "dialect": dialect,
    }).json()
    assert preview["values_found"]["account"]["distinct"] == ["Checking"]
    assert preview["dialect"]["decimal_separator"] == ","

    resp = c.post("/import/mapped", json={
        "filename": preview["filename"], "target_scenario_id": preview["target_scenario_id"],
        "file_content_b64": preview["file_content_b64"], "shape": preview["shape"],
        "column_map": preview["column_map"], "dialect": preview["dialect"],
        "value_maps": {"account": {"Checking": book["checking"]["code"]},
                        "category": {service.IMPORT_NO_VALUE_KEY: book["rent"]["code"]}},
        "flip_sign": False,
    })
    assert resp.status_code == 200
    assert resp.json()["staged_count"] == 1


def test_import_mapped_commit_endpoint_stages_a_grouped_debit_credit_file(book, conn):
    # IMPORT_WIZARD.md §7 Phase 4 — the plain importer's own shape,
    # driven end to end through the unified `/mapped/*` endpoints.
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Rent,{book['checking']['code']},,500",
        f"1,2026-08-01,Rent,{book['rent']['code']},500,",
    )
    c = client_for(conn)
    columns = c.post(
        "/import/mapped/columns", data={"target_scenario_id": str(book["actual"]["id"])},
        files={"file": ("export.csv", content, "text/csv")}).json()
    shape = columns["shape"]
    assert shape["rows_per_entry"] == "grouped" and shape["amount_style"] == "debit_credit"
    column_map = {"group_key": "Entry #", "account": "Account code", "date": "Date",
                   "description": "Description", "debit": "Debit", "credit": "Credit"}

    resp = c.post("/import/mapped", json={
        "filename": columns["filename"], "target_scenario_id": columns["target_scenario_id"],
        "file_content_b64": columns["file_content_b64"], "shape": shape, "column_map": column_map,
        "column_kinds": {"account": "code"}, "value_maps": {}, "flip_sign": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_count"] == 1
    assert body["errors"] == []
