"""The scheduling module's `APIRouter` — scheduled entries and entry
templates. Mirrors `modules/reference/router.py`'s shape: this module
also bundles two legacy top-level resources, so it carries no single
`prefix` — each route spells out its own full legacy path (`/scheduled`,
`/templates`) directly.

**No route for `service.materialize_due_schedules`.** Legacy has none
either — it runs implicitly, once per request, from auth middleware
(see `service.py`'s own docstring for why that stays unwired here).
Nothing in this router calls it.

**Every write route here catches `(ValueError, SQLAlchemyError)` as a
400** — same settled convention `modules/entries/`, `/staging/`,
`/budget/`, `/imports/`, and `/reference/` all already use; a "not
found" id is client-supplied-bad-input, not a routing-level 404.

**No CSRF check, no real `imported_by`/attribution equivalent** — same
`modules/auth/` (Phase 1.11) gap every prior write module documents.
Neither `scheduled_entries` nor `entry_templates` has a user-attribution
column at all (unlike `journal_entries.created_by_user_id`), so this
gap is narrower here than for `entries`/`staging`/`imports` — there's
nothing to leave `NULL`, just no audit trail to add.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from . import schemas, service

router = APIRouter(tags=["scheduling"])


def _bad_request(e: Exception) -> HTTPException:
    detail = pg_message(e) if isinstance(e, SQLAlchemyError) else str(e)
    return HTTPException(400, detail=detail)


# ---------------------------------------------------------------------------
# Scheduled entries
# ---------------------------------------------------------------------------

@router.get("/scheduled")
def list_schedules(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_schedules(conn)


@router.post("/scheduled", status_code=201)
def create_schedule(payload: schemas.CreateScheduleRequest,
                     conn: Connection = Depends(get_connection)) -> dict:
    accounts = [ln.account for ln in payload.lines]
    debits = [ln.debit for ln in payload.lines]
    credits = [ln.credit for ln in payload.lines]
    memos = [ln.memo or "" for ln in payload.lines]
    try:
        sched_id = service.create_schedule(
            conn, description=payload.description, reference=payload.reference,
            payee_id=payload.payee_id, target_scenario_id=payload.target_scenario_id,
            interval_unit=payload.interval_unit, interval_count=payload.interval_count,
            next_date=payload.next_date, tags=payload.tags,
            accounts=accounts, debits=debits, credits=credits, memos=memos)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": sched_id}


@router.post("/scheduled/{scheduled_id}/toggle-active")
def toggle_schedule_active(scheduled_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_schedule_active(conn, scheduled_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


# ---------------------------------------------------------------------------
# Entry templates
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_templates(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_templates(conn)


@router.post("/templates", status_code=201)
def create_template(payload: schemas.CreateTemplateRequest,
                     conn: Connection = Depends(get_connection)) -> dict:
    accounts = [ln.account for ln in payload.lines]
    debits = [ln.debit for ln in payload.lines]
    credits = [ln.credit for ln in payload.lines]
    memos = [ln.memo or "" for ln in payload.lines]
    try:
        tpl_id = service.create_template(
            conn, name=payload.name, description=payload.description,
            reference=payload.reference, payee_id=payload.payee_id, tags=payload.tags,
            accounts=accounts, debits=debits, credits=credits, memos=memos)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": tpl_id}


@router.post("/templates/{template_id}/delete")
def delete_template(template_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        service.delete_template(conn, template_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": template_id}
