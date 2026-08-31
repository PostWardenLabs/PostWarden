"""The reference module's `APIRouter` — Accounts, Account levels,
Scenarios, Payees, Tags. Mirrors `modules/entries/router.py`'s shape
(thin routes, real logic in `service.py`, a Pydantic body on every write
route) with one structural difference: this router bundles five legacy
top-level resources rather than one, so it carries no single `prefix` —
each route spells out its own full legacy path (`/accounts`, `/payees`,
...) directly, the same paths `app/main.py` already used.

**Every write route catches `(ValueError, SQLAlchemyError)`, always as a
400 — never a 404.** Legacy catches `(ValueError, psycopg.Error)`
identically on every single write route in `app/main.py`, `_pg_msg`-ing
whichever one it was, with no status-code distinction at all (a
redirect-plus-flash has no such thing). `modules/entries/`,
`modules/staging/`, `modules/budget/`, and `modules/imports/` all
already settled on 400-always for the JSON-API equivalent — a "not
found" id is a client-supplied-bad-input problem the same shape as any
other validation failure, not a routing-level 404. `_bad_request` below
exists because, unlike those four modules, *every* write route here (not
just some) needs the identical two-exception mapping — Accounts/
Scenarios/Account levels/Payees/Tags share no other structure, but they
share this.

**Mounted into `app` as of Phase 1.14 (`main.py`):** every route now
requires `get_current_session` (router-level, legacy's global `auth_
gate` equivalent), and every write route additionally requires `require_
csrf_header`. None of these five resources carry a user-attribution
column, so every write route gains the dependency as a bare
`dependencies=[...]` entry, not a bound parameter — same shape `modules/
budget/router.py`'s own `save_cell` uses for the identical reason.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from ..auth.deps import get_current_session, require_csrf_header
from . import schemas, service

router = APIRouter(tags=["reference"], dependencies=[Depends(get_current_session)])


def _bad_request(e: Exception) -> HTTPException:
    detail = pg_message(e) if isinstance(e, SQLAlchemyError) else str(e)
    return HTTPException(400, detail=detail)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@router.get("/accounts")
def list_accounts(level_id: int | None = None, conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_accounts(conn, level_id)


@router.post("/accounts", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_account(payload: schemas.CreateAccountRequest,
                    conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.create_account(
            conn, code=payload.code, name=payload.name, account_type=payload.account_type,
            parent_id=payload.parent_id, is_postable=payload.is_postable,
            is_cashflow=payload.is_cashflow)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/accounts/quick-create", status_code=201, dependencies=[Depends(require_csrf_header)])
def quick_create_account(payload: schemas.QuickCreateAccountRequest,
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.quick_create_account(
            conn, name=payload.name, parent_id=payload.parent_id,
            account_type=payload.account_type, is_postable=payload.is_postable)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/accounts/{account_id}/toggle-active", dependencies=[Depends(require_csrf_header)])
def toggle_account_active(account_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_account_active(conn, account_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/accounts/{account_id}/toggle-cashflow", dependencies=[Depends(require_csrf_header)])
def toggle_account_cashflow(account_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_account_cashflow(conn, account_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

@router.get("/account-levels")
def list_account_levels(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_account_levels(conn)


@router.post("/account-levels", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_account_level(payload: schemas.CreateAccountLevelRequest,
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.create_account_level(conn, payload.name, payload.depth)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/account-levels/{level_id}/rename", dependencies=[Depends(require_csrf_header)])
def rename_account_level(level_id: int, payload: schemas.RenameRequest,
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        name = service.rename_account_level(conn, level_id, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": level_id, "name": name}


@router.post("/account-levels/{level_id}/delete", dependencies=[Depends(require_csrf_header)])
def delete_account_level(level_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        service.delete_account_level(conn, level_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": level_id}


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@router.get("/scenarios")
def list_scenarios(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_scenarios(conn)


@router.post("/scenarios", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_scenario(payload: schemas.CreateScenarioRequest,
                     conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.create_scenario(
            conn, code=payload.code, name=payload.name, scenario_type=payload.scenario_type,
            enforce_balance=payload.enforce_balance,
            income_statement_only=payload.income_statement_only,
            base_level_id=payload.base_level_id, notes=payload.notes)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/scenarios/{scenario_id}/toggle-lock", dependencies=[Depends(require_csrf_header)])
def toggle_scenario_lock(scenario_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_scenario_lock(conn, scenario_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

@router.get("/payees")
def list_payees(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_payees(conn)


@router.post("/payees", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_payee(payload: schemas.CreatePayeeRequest,
                  conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.create_payee(conn, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/payees/quick-create", status_code=201, dependencies=[Depends(require_csrf_header)])
def quick_create_payee(payload: schemas.CreatePayeeRequest,
                        conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.quick_create_payee(conn, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/payees/{payee_id}/toggle-active", dependencies=[Depends(require_csrf_header)])
def toggle_payee_active(payee_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_payee_active(conn, payee_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/payees/{payee_id}/rename", dependencies=[Depends(require_csrf_header)])
def rename_payee(payee_id: int, payload: schemas.RenameRequest,
                  conn: Connection = Depends(get_connection)) -> dict:
    try:
        name = service.rename_payee(conn, payee_id, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": payee_id, "name": name}


@router.post("/payees/{payee_id}/delete", dependencies=[Depends(require_csrf_header)])
def delete_payee(payee_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        name = service.delete_payee(conn, payee_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": payee_id, "name": name}


@router.post("/payees/merge", dependencies=[Depends(require_csrf_header)])
def merge_payees(payload: schemas.MergePayeesRequest,
                  conn: Connection = Depends(get_connection)) -> dict:
    try:
        merged, affected = service.merge_payees(conn, payload.payee_ids, payload.target_name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"merged": merged, "entries_affected": affected, "name": payload.target_name}


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("/tags")
def list_tags(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.list_tags(conn)


@router.post("/tags", status_code=201, dependencies=[Depends(require_csrf_header)])
def create_tag(payload: schemas.CreateTagRequest, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.create_tag(conn, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/tags/{tag_id}/toggle-active", dependencies=[Depends(require_csrf_header)])
def toggle_tag_active(tag_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        return service.toggle_tag_active(conn, tag_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)


@router.post("/tags/{tag_id}/rename", dependencies=[Depends(require_csrf_header)])
def rename_tag(tag_id: int, payload: schemas.RenameRequest,
                conn: Connection = Depends(get_connection)) -> dict:
    try:
        name = service.rename_tag(conn, tag_id, payload.name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": tag_id, "name": name}


@router.post("/tags/{tag_id}/delete", dependencies=[Depends(require_csrf_header)])
def delete_tag(tag_id: int, conn: Connection = Depends(get_connection)) -> dict:
    try:
        name = service.delete_tag(conn, tag_id)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"id": tag_id, "name": name}


@router.post("/tags/merge", dependencies=[Depends(require_csrf_header)])
def merge_tags(payload: schemas.MergeTagsRequest, conn: Connection = Depends(get_connection)) -> dict:
    try:
        merged, affected = service.merge_tags(conn, payload.tag_ids, payload.target_name)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"merged": merged, "entries_affected": affected, "name": payload.target_name}
