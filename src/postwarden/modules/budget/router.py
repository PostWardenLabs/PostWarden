"""The budget module's `APIRouter` — the Budget grid backend. Same shape
`modules/reports/router.py`/`modules/entries/router.py` already
established: thin routes, real logic in `service.py`.

`get_current_session` is required at the router level for every route,
and `POST /budget/cell` additionally requires `require_csrf_header`.
`budget_lines` carries no user-attribution column at all, so there's
nothing for `save_cell` to thread a `session["user_id"]` into; it gains
the dependency as a bare `dependencies=[...]` entry, not a bound
parameter.

**No scenario picker here.** The list of income-statement-only scenarios
to populate a picker with lives in `modules/reference/` — reaching into
it would break the "deletable on its own" test a vertical slice is held
to, the same reasoning `modules/reports/router.py`'s own docstring
applies. `GET /budget` never picks a *default* scenario when `scenario`
is omitted, for exactly that reason: doing so needs the full scenario
list, which lives in another module. The frontend resolves a default
from `modules/reference/`'s own scenario list; an empty/unresolved
`scenario` here just returns `service.budget_grid`'s zero-figure stub,
same as a scenario code that doesn't exist or isn't
income-statement-only."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...domain.periods import month_options, shift_month
from ...errors import pg_message
from ..auth.deps import get_current_session, require_csrf_header
from . import schemas, service

router = APIRouter(prefix="/budget", tags=["budget"],
                    dependencies=[Depends(get_current_session)])


def _resolve_month(month: str) -> str:
    """Normalizes the `month` query param to a real `YYYY-MM-01` string,
    defaulting to the current month. `len(...) == 7` covers the plain
    `YYYY-MM` shape the Month combobox and prev/next links actually
    send; a `ValueError` from
    `date.fromisoformat` (a stale bookmark, a hand-edited query string —
    BACKLOG.md's own note on why the grid's own month picker is a real
    `<select>`-equivalent and not a raw date input) falls back to today's
    month rather than a 500, same "don't crash on a bad filter value"
    leniency every other report's own date parsing already gets."""
    month_in = month or date.today().isoformat()
    if len(month_in) == 7:
        month_in += "-01"
    try:
        return date.fromisoformat(month_in).replace(day=1).isoformat()
    except ValueError:
        return date.today().replace(day=1).isoformat()


@router.get("")
def budget_grid(scenario: str = "", month: str = "", pct_of_base: int = 0,
                 conn: Connection = Depends(get_connection)) -> dict:
    month = _resolve_month(month)
    # -36..+36 months around *today*, not the currently selected month —
    # see domain.periods.month_options's own docstring for why. Widened
    # to include the resolved month itself when paging (or a bookmarked
    # link) lands past that window's own edge — keeps it selectable
    # rather than silently falling back to nothing matching.
    options = month_options()
    if month[:7] not in options:
        options = sorted(set(options) | {month[:7]})
    result = service.budget_grid(conn, scenario, month, bool(pct_of_base))
    return {
        **result, "scenario": scenario, "month": month, "month_options": options,
        "prev_month": shift_month(month, -1), "next_month": shift_month(month, 1),
        "pct_of_base": pct_of_base,
    }


@router.post("/cell", dependencies=[Depends(require_csrf_header)])
def save_cell(payload: schemas.SaveCellRequest, conn: Connection = Depends(get_connection)) -> dict:
    try:
        amount = service.save_budget_cell(
            conn, scenario_id=payload.scenario_id, account_code=payload.account,
            period_month=payload.period_month, amount_raw=payload.amount)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return {"amount": amount}
