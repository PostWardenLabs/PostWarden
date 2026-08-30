"""The entries module's `APIRouter` — the Journal backend. Mirrors
`modules/reports/router.py`'s shape (thin routes, real logic in
`service.py`) with one real difference: every write route here needs a
Pydantic body (`schemas.py`), not just query params — REBUILD.md
decision 3's own named example of why entries has one and reports
doesn't.

Mounted into `app` as of Phase 1.14 (`main.py`), which closes the gap
this docstring used to flag: **every route now requires `get_current_
session` (set at the router level, the equivalent of legacy's global
`auth_gate`), and every write route additionally requires `require_csrf_
header`.** `create_entry`/`reverse_entry`/`reverse_entries_bulk` bind the
resulting `session` and thread `session["user_id"]` through to
`service.py` as `created_by_user_id`/`user_id` — the same columns that
sat `NULL` before this phase now get a real value, matching legacy's own
`auth.current_user(request)["user_id"]` at each of those three call
sites. The other write routes here (`edit_entries_tags`, `edit_entry_
description`, `edit_line_memo`) need the CSRF check but never touched
attribution in legacy either, so they only gain `require_csrf_header` as
a bare `dependencies=[...]` entry, not a bound parameter.

**CSV/XLSX export routes landed in Phase 1.12**, alongside the shared
`export/` module: `GET /entries/export.csv`/`.xlsx` reuse `service.
export_rows`/`repository.build_filter` — the exact same filters and
`WHERE` clause `GET /entries` itself uses — so what's on screen is
always what gets exported."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from ..auth.deps import get_current_session, require_csrf_header
from . import export, schemas, service

router = APIRouter(prefix="/entries", tags=["entries"],
                    dependencies=[Depends(get_current_session)])


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


@router.get("/export.csv")
def export_csv(scenario: str = "", date_from: str = "", date_to: str = "", qtext: str = "",
                tags: str = "", account: str = "", payee: str = "", amount_op: str = "",
                amount_value: str = "", amount_value2: str = "", hide_reversed: int = 0,
                entry_id: str = "", conn: Connection = Depends(get_connection)):
    """Every entry matching the current filters (not just the current
    page) — one row per journal line, so it opens straight into a
    spreadsheet without the entry/line grouping `GET /entries` itself
    returns."""
    rows = service.export_rows(
        conn, scenario=scenario, date_from=date_from, date_to=date_to, qtext=qtext, tags=tags,
        account=account, payee=payee, amount_op=amount_op, amount_value=amount_value,
        amount_value2=amount_value2, hide_reversed=bool(hide_reversed), entry_id=entry_id)
    return export.journal_csv(rows)


@router.get("/export.xlsx")
def export_xlsx(scenario: str = "", date_from: str = "", date_to: str = "", qtext: str = "",
                 tags: str = "", account: str = "", payee: str = "", amount_op: str = "",
                 amount_value: str = "", amount_value2: str = "", hide_reversed: int = 0,
                 entry_id: str = "", conn: Connection = Depends(get_connection)):
    rows = service.export_rows(
        conn, scenario=scenario, date_from=date_from, date_to=date_to, qtext=qtext, tags=tags,
        account=account, payee=payee, amount_op=amount_op, amount_value=amount_value,
        amount_value2=amount_value2, hide_reversed=bool(hide_reversed), entry_id=entry_id, group_legs=True)
    return export.journal_xlsx(rows, scenario, date_from, date_to)


@router.post("", status_code=201)
def create_entry(payload: schemas.CreateEntryRequest,
                  session: dict = Depends(require_csrf_header),
                  conn: Connection = Depends(get_connection)) -> dict:
    accounts = [ln.account for ln in payload.lines]
    debits = [ln.debit for ln in payload.lines]
    credits = [ln.credit for ln in payload.lines]
    memos = [ln.memo or "" for ln in payload.lines]
    try:
        entry_id = service.create_entry(
            conn, entry_date=payload.entry_date, scenario_id=payload.scenario_id,
            description=payload.description, reference=payload.reference, tags=payload.tags,
            payee_id=payload.payee_id, accounts=accounts, debits=debits, credits=credits,
            memos=memos, created_by_user_id=session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"entry_id": entry_id}


@router.post("/{entry_id}/reverse")
def reverse_entry(entry_id: str, session: dict = Depends(require_csrf_header),
                   conn: Connection = Depends(get_connection)) -> dict:
    try:
        new_id = service.reverse_entry(conn, entry_id, session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"entry_id": entry_id, "reversed_by": new_id}


@router.post("/reverse")
def reverse_entries_bulk(payload: schemas.ReverseEntriesRequest,
                          session: dict = Depends(require_csrf_header),
                          conn: Connection = Depends(get_connection)) -> dict:
    if not payload.entry_ids:
        raise HTTPException(400, detail="Select at least one entry to reverse")
    reversed_ids, errors = service.reverse_entries_bulk(conn, payload.entry_ids, session["user_id"])
    return {"reversed": reversed_ids, "errors": errors}


@router.post("/tags", dependencies=[Depends(require_csrf_header)])
def edit_entries_tags(payload: schemas.EditTagsRequest, conn: Connection = Depends(get_connection)) -> dict:
    try:
        tag_name = service.edit_entries_tags(conn, payload.entry_ids, payload.action, payload.tag)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"tag": tag_name, "action": payload.action}


@router.post("/{entry_id}/edit-description", dependencies=[Depends(require_csrf_header)])
def edit_entry_description(entry_id: str, payload: schemas.EditDescriptionRequest,
                            conn: Connection = Depends(get_connection)) -> dict:
    try:
        description = service.edit_description(conn, entry_id, payload.description)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"entry_id": entry_id, "description": description}


@router.post("/lines/{line_id}/edit-memo", dependencies=[Depends(require_csrf_header)])
def edit_line_memo(line_id: int, payload: schemas.EditMemoRequest,
                    conn: Connection = Depends(get_connection)) -> dict:
    try:
        memo = service.edit_line_memo(conn, line_id, payload.memo)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"line_id": line_id, "memo": memo}
