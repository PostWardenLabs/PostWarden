"""The entries module's `APIRouter` — the Journal backend. Mirrors
`modules/reports/router.py`'s shape (thin routes, real logic in
`service.py`) with one real difference: every write route here needs a
Pydantic body (`schemas.py`), not just query params — REBUILD.md
decision 3's own named example of why entries has one and reports
doesn't.

Deliberately not yet mounted into `app` — same as `modules/reports/
router.py`; real mounting is Phase 1.14, once every module in
`modules/` has built one.

**Two things this router does NOT do yet, both documented gaps a later
phase closes rather than something reached into now** (same "don't
depend on a module that doesn't exist yet" reasoning `modules/reports/
router.py` already applied to `modules/reference/`):

- **No CSRF check, no real `created_by_user_id`/reversed-by
  attribution.** Legacy's `require_csrf`/`auth.current_user(request)`
  are both `modules/auth/` (Phase 1.11) concerns. Every write route here
  posts with `created_by_user_id = NULL` — the column is nullable for
  exactly this reason (`db/schema.sql`'s own comment: "nullable so
  direct psql/import inserts don't need a user, but the app always sets
  it from the session"). Phase 1.11 wires a real dependency in here;
  until then, anyone who can reach this router can post as this app
  layer's own version of a direct-SQL insert.
- **No CSV/XLSX export routes.** `entries_export_csv`/`entries_export_
  xlsx` share `_entries_filter` with the paged view but write through
  `csv.writer`/openpyxl helpers that belong to the shared `export/`
  module (Phase 1.12). `service.list_entries`/`repository.build_filter`
  are already shaped so 1.12 can reuse them unchanged — same filters,
  same WHERE clause — the way legacy's own `_entries_filter` was shared
  three ways.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from . import schemas, service

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("")
def list_entries(scenario: str = "", date_from: str = "", date_to: str = "", qtext: str = "",
                  tags: str = "", account: str = "", payee: str = "", amount_op: str = "",
                  amount_value: str = "", amount_value2: str = "", hide_reversed: int = 0,
                  entry_id: str = "", page: int = 1,
                  conn: Connection = Depends(get_connection)) -> dict:
    return service.list_entries(
        conn, scenario=scenario, date_from=date_from, date_to=date_to, qtext=qtext, tags=tags,
        account=account, payee=payee, amount_op=amount_op, amount_value=amount_value,
        amount_value2=amount_value2, hide_reversed=bool(hide_reversed), entry_id=entry_id,
        page=page)


@router.post("", status_code=201)
def create_entry(payload: schemas.CreateEntryRequest, conn: Connection = Depends(get_connection)) -> dict:
    accounts = [ln.account for ln in payload.lines]
    debits = [ln.debit for ln in payload.lines]
    credits = [ln.credit for ln in payload.lines]
    memos = [ln.memo or "" for ln in payload.lines]
    try:
        entry_id = service.create_entry(
            conn, entry_date=payload.entry_date, scenario_id=payload.scenario_id,
            description=payload.description, reference=payload.reference, tags=payload.tags,
            payee_id=payload.payee_id, accounts=accounts, debits=debits, credits=credits,
            memos=memos)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"entry_id": entry_id}


@router.post("/{entry_id}/reverse")
def reverse_entry(entry_id: str, conn: Connection = Depends(get_connection)) -> dict:
    try:
        new_id = service.reverse_entry(conn, entry_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"entry_id": entry_id, "reversed_by": new_id}


@router.post("/reverse")
def reverse_entries_bulk(payload: schemas.ReverseEntriesRequest,
                          conn: Connection = Depends(get_connection)) -> dict:
    if not payload.entry_ids:
        raise HTTPException(400, detail="Select at least one entry to reverse")
    reversed_ids, errors = service.reverse_entries_bulk(conn, payload.entry_ids)
    return {"reversed": reversed_ids, "errors": errors}


@router.post("/tags")
def edit_entries_tags(payload: schemas.EditTagsRequest, conn: Connection = Depends(get_connection)) -> dict:
    try:
        tag_name = service.edit_entries_tags(conn, payload.entry_ids, payload.action, payload.tag)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"tag": tag_name, "action": payload.action}


@router.post("/{entry_id}/edit-description")
def edit_entry_description(entry_id: str, payload: schemas.EditDescriptionRequest,
                            conn: Connection = Depends(get_connection)) -> dict:
    try:
        description = service.edit_description(conn, entry_id, payload.description)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"entry_id": entry_id, "description": description}


@router.post("/lines/{line_id}/edit-memo")
def edit_line_memo(line_id: int, payload: schemas.EditMemoRequest,
                    conn: Connection = Depends(get_connection)) -> dict:
    try:
        memo = service.edit_line_memo(conn, line_id, payload.memo)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"line_id": line_id, "memo": memo}
