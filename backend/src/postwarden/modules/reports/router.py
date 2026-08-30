"""The reports module's `APIRouter` — five read-only GET endpoints, one
per report, each a thin wrapper: resolve query params/defaults, call
`service.py`, add the prev/next date-navigation fields every point-in-
time or range report shows (`domain.periods`), return the result as a
plain dict.

Deliberately not yet mounted into `app` — see `main.py`'s own docstring:
real router mounting is Phase 1.14, once every module in `modules/` has
built one. This file is fully testable on its own in the meantime (a
throwaway `FastAPI()` + `include_router()`, the same pattern
`test_json.py` already established for an unmounted route), and its
Decimal/date fields serialize correctly with no extra wiring here —
`configure_decimal_encoding()` runs once at `main.py` import time and
patches FastAPI's `jsonable_encoder` process-wide, which is what
actually renders every plain-dict return below (see `json.py`'s own
docstring for why an *explicit* `JSONResponse(...)` would need a second,
different fix that no route here happens to need).

No `schemas.py` in this module, unlike `modules/entries/`
(REBUILD.md decision 3's own example) — every route here is a GET with
plain query params FastAPI already validates from the function
signature, and no request body ever needs a Pydantic model. Response
shapes stay plain dicts, same as `domain/`'s own functions return —
there is no reference-data picker (`scenarios`, `account_levels`) folded
into a report response either: those belong to `modules/reference/`
(Phase 1.9), and a report route reaching into a module that doesn't
exist yet would break the "deletable on its own" test REBUILD.md
decision 3 sets for a vertical slice.
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Connection

from ...db import get_connection
from ...domain.periods import shift_date_by_month, shift_range, split_periods
from . import service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/trial-balance")
def trial_balance(scenario: str = "ACTUAL", as_of: str = "", zeros: int = 0, raw: int = 0,
                   conn: Connection = Depends(get_connection)) -> dict:
    result = service.trial_balance(conn, scenario, as_of or None, zeros, raw)
    as_of_date = as_of or date.today().isoformat()
    return {
        **result, "scenario": scenario, "as_of": as_of, "zeros": zeros, "raw": raw,
        "prev_as_of": shift_date_by_month(as_of_date, -1),
        "next_as_of": shift_date_by_month(as_of_date, 1),
        "today": date.today().isoformat(),
    }


@router.get("/balance-sheet")
def balance_sheet(scenario: str = "ACTUAL", as_of: str = "", raw: int = 0, zeros: int = 0,
                   conn: Connection = Depends(get_connection)) -> dict:
    result = service.balance_sheet(conn, scenario, as_of or None, raw, zeros)
    as_of_date = as_of or date.today().isoformat()
    return {
        **result, "scenario": scenario, "as_of": as_of, "raw": raw, "zeros": zeros,
        "prev_as_of": shift_date_by_month(as_of_date, -1),
        "next_as_of": shift_date_by_month(as_of_date, 1),
        "today": date.today().isoformat(),
    }


@router.get("/income-statement")
def income_statement(scenario: str = "ACTUAL", compare: str = "", date_from: str = "", date_to: str = "",
                      zeros: int = 0, pct_of_base: int = 0, split: str = "",
                      conn: Connection = Depends(get_connection)) -> dict:
    today = date.today()
    date_from = date_from or today.replace(day=1).isoformat()
    date_to = date_to or today.isoformat()
    periods = split_periods(date_from, date_to, split)
    if periods:
        result = service.income_statement_matrix(conn, scenario, periods, date_from, date_to, compare, zeros,
                                                   bool(pct_of_base))
    else:
        result = service.income_statement_rows(conn, scenario, date_from, date_to, compare, zeros,
                                                 bool(pct_of_base))
        result["periods"] = periods
    prev_from, prev_to, next_from, next_to = shift_range(date_from, date_to)
    return {
        **result, "scenario": scenario, "compare": compare, "date_from": date_from, "date_to": date_to,
        "zeros": zeros, "pct_of_base": pct_of_base, "split": split, "today": today.isoformat(),
        "prev_from": prev_from, "prev_to": prev_to, "next_from": next_from, "next_to": next_to,
    }


@router.get("/cash-flow")
def cash_flow(scenario: str = "ACTUAL", date_from: str = "", date_to: str = "",
              conn: Connection = Depends(get_connection)) -> dict:
    today = date.today()
    date_from = date_from or today.replace(day=1).isoformat()
    date_to = date_to or today.isoformat()
    result = service.cash_flow_rows(conn, scenario, date_from, date_to)
    prev_from, prev_to, next_from, next_to = shift_range(date_from, date_to)
    return {
        **result, "scenario": scenario, "date_from": date_from, "date_to": date_to, "today": today.isoformat(),
        "prev_from": prev_from, "prev_to": prev_to, "next_from": next_from, "next_to": next_to,
    }


@router.get("/variance")
def variance(baseline: str = "ACTUAL", compare: str = "", level_id: str = "", as_of: str = "",
             zeros: int = 0, pct_of_base: int = 0, conn: Connection = Depends(get_connection)) -> dict:
    result = service.compute_variance(conn, baseline, compare, level_id, as_of or None, zeros, bool(pct_of_base))
    as_of_date = as_of or date.today().isoformat()
    return {
        **result, "baseline": baseline, "as_of": as_of, "zeros": zeros, "pct_of_base": pct_of_base,
        "prev_as_of": shift_date_by_month(as_of_date, -1),
        "next_as_of": shift_date_by_month(as_of_date, 1),
        "today": date.today().isoformat(),
    }
