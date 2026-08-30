"""The staging module's `APIRouter` — the layover a scheduled entry's
occurrence or a CSV import row sits in until approved. Same shape
`modules/entries/router.py` established: thin routes, real logic in
`service.py`.

Deliberately not yet mounted into `app` — real mounting is Phase 1.14,
once every module in `modules/` has built one.

**Same two documented gaps `modules/entries/router.py` already carries,
for the same reason (`modules/auth/`, Phase 1.11, doesn't exist yet):**
no CSRF check, and no real `created_by_user_id` attribution on an
approved entry — every approve posts with `created_by_user_id = NULL`.
No CSV import routes either: `_parse_csv_import` and the two importer
flows (plain CSV, mapped/rules) belong to `modules/imports/` (Phase
1.8), which produces the `import_batches`/staged `journal_entries` rows
this module only ever reads and acts on."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from . import schemas, service

router = APIRouter(prefix="/staging", tags=["staging"])


@router.get("")
def list_pending(date_from: str = "", date_to: str = "", qtext: str = "", tags: str = "",
                  account: str = "", payee: str = "", amount_op: str = "", amount_value: str = "",
                  amount_value2: str = "", target_scenario: str = "",
                  conn: Connection = Depends(get_connection)) -> dict:
    return service.list_pending(
        conn, date_from=date_from, date_to=date_to, qtext=qtext, tags=tags, account=account,
        payee=payee, amount_op=amount_op, amount_value=amount_value, amount_value2=amount_value2,
        target_scenario=target_scenario)


@router.post("/approve")
def approve_entries(payload: schemas.ApproveRejectRequest,
                     conn: Connection = Depends(get_connection)) -> dict:
    if not payload.entry_ids:
        raise HTTPException(400, detail="Select at least one entry to approve")
    approved, errors = service.approve_entries(conn, payload.entry_ids)
    return {"approved": approved, "errors": errors}


@router.get("/{entry_id}/edit")
def get_edit_data(entry_id: str, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.get_edit_data(conn, entry_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/{entry_id}/edit")
def save_edit(entry_id: str, payload: schemas.EditStagingEntryRequest,
              conn: Connection = Depends(get_connection)) -> dict:
    accounts = [ln.account for ln in payload.lines]
    debits = [ln.debit for ln in payload.lines]
    credits = [ln.credit for ln in payload.lines]
    memos = [ln.memo or "" for ln in payload.lines]
    try:
        service.save_edit(
            conn, entry_id, entry_date=payload.entry_date, description=payload.description,
            reference=payload.reference, payee_id=payload.payee_id, tags=payload.tags,
            accounts=accounts, debits=debits, credits=credits, memos=memos)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"entry_id": entry_id}


@router.post("/{entry_id}/reject")
def reject_entry(entry_id: str, conn: Connection = Depends(get_connection)) -> dict:
    try:
        service.reject_entry(conn, entry_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"entry_id": entry_id}


@router.post("/reject")
def reject_entries(payload: schemas.ApproveRejectRequest,
                    conn: Connection = Depends(get_connection)) -> dict:
    if not payload.entry_ids:
        raise HTTPException(400, detail="Select at least one entry to reject")
    rejected, errors = service.reject_entries(conn, payload.entry_ids)
    return {"rejected": rejected, "errors": errors}


@router.get("/duplicates")
def find_duplicates(conn: Connection = Depends(get_connection)) -> dict:
    return {"groups": service.find_duplicate_groups(conn)}


@router.post("/duplicates/merge")
def merge_duplicates(payload: schemas.MergeDuplicatesRequest,
                      conn: Connection = Depends(get_connection)) -> dict:
    try:
        service.merge_duplicates(
            conn, keep_id=payload.keep_id, remove_ids=payload.remove_ids,
            description=payload.description, reference=payload.reference,
            payee_id=payload.payee_id, tags=payload.tags, line_memos=payload.line_memos)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"kept_entry_id": payload.keep_id}
