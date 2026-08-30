"""The analytics module's `APIRouter` — the five `/api/*` JSON-mirror
routes plus the two Connect BI settings routes (see `service.py`'s own
docstring for why the latter live here). No single `prefix` fits both
families, so every route spells out its own full path, the same
"bundles more than one legacy top-level concern" shape `modules/
reference/router.py` (Phase 1.9) and `modules/auth/router.py` (Phase
1.11) already established.

No `schemas.py`, same reasoning `modules/reports/router.py` (Phase 1.4)
already gives: every route here is a GET with plain query params FastAPI
already validates from the function signature, and no request body ever
needs a Pydantic model.

Deliberately not yet mounted into `app` — real router mounting is Phase
1.14, once every module in `modules/` (and this package) has built one.
"""
import json as stdlib_json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.engine import Connection

from ..config import Settings, get_settings
from ..db import get_connection
from . import service

router = APIRouter(tags=["analytics"])


# ---------------------------------------------------------------------------
# /api/* — same data as the report/entry screens, for scripts.
# ---------------------------------------------------------------------------

@router.get("/api/trial-balance")
def api_trial_balance(scenario: str = "ACTUAL", as_of: str | None = None,
                       conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.trial_balance(conn, scenario, as_of)


@router.get("/api/accounts")
def api_accounts(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.accounts(conn)


@router.get("/api/scenarios")
def api_scenarios(conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.scenarios(conn)


@router.get("/api/entries")
def api_entries(scenario: str | None = None, date_from: str | None = None, date_to: str | None = None,
                 conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.entries(conn, scenario, date_from, date_to)


@router.get("/api/monthly-activity")
def api_monthly_activity(scenario: str | None = None,
                          conn: Connection = Depends(get_connection)) -> list[dict]:
    return service.monthly_activity(conn, scenario)


# ---------------------------------------------------------------------------
# Connect BI — the Settings screen's read-only-role connection info.
# ---------------------------------------------------------------------------

@router.get("/settings/connect-bi")
def connect_bi(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    return service.connect_bi_info(request.url.hostname, settings)


@router.get("/settings/connect-bi/download.pbids")
def connect_bi_pbids(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    pbids = service.pbids_document(request.url.hostname, settings)
    return Response(
        stdlib_json.dumps(pbids, indent=2), media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="PostWarden.pbids"'},
    )
