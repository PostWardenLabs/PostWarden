"""The custom-reports `APIRouter` — one read-only GET plus its
`.csv`/`.xlsx` export siblings, all under `/reports/custom` (a path no
route in `modules/reports/` uses; the two modules stay independent
slices that happen to share a URL neighborhood — see `SPEC.md`
decision 25).

The whole report config lives in the query string, deliberately: a GET
with the config in the URL is what makes any custom report
bookmarkable/shareable with zero save machinery, and is the bridge to
v2's `saved_reports` (a saved report is essentially a named, validated
query string). `metric`/`dimension`/`account_type` are enum-typed
straight in the signature, so FastAPI 422s out-of-allowlist values
before any code runs and the generated frontend client gets them as
TypeScript union types — see `enums.py`'s docstring.

Unlike the classic reports' GETs, a blank date range here means
*unbounded* on the read route too, not "this month" — a custom report
over all history is a sensible default view, so the read route and its
export siblings agree for free (contrast `modules/reports/router.py`'s
own docstring on why its two range reports diverge from their exports).
`prev_*`/`next_*` navigation fields are only computed when both dates
are set — shifting an unbounded range has no meaning.

Same auth shape as `modules/reports/`: `get_current_session` required
at the router level, no write routes, so no `require_csrf_header`
anywhere. `service.py` raises `ValueError` on anything the type system
couldn't catch (an id naming no row, a malformed date, a missing
`level_id`); the routes convert that to a plain 400.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection

from ...db import get_connection
from ...domain.periods import shift_range
from ..auth.deps import get_current_session
from . import export, service
from .enums import AccountTypeFilter, Dimension, Metric

router = APIRouter(prefix="/reports", tags=["custom-reports"],
                   dependencies=[Depends(get_current_session)])


def _run(conn: Connection, metric: Metric, dimension: Dimension, scenario: str,
         date_from: str, date_to: str, account_id: int | None, subtree: int,
         tag_id: int | None, payee_id: int | None,
         account_type: AccountTypeFilter | None, level_id: int | None) -> dict:
    """Shared by the read route and both export siblings — identical
    resolution, per this module's docstring."""
    try:
        return service.run(conn, metric=metric, dimension=dimension, scenario=scenario,
                           date_from=date_from, date_to=date_to, account_id=account_id,
                           subtree=bool(subtree), tag_id=tag_id, payee_id=payee_id,
                           account_type=account_type, level_id=level_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from None


@router.get("/custom")
def custom_report(metric: Metric = Metric.net_amount, dimension: Dimension = Dimension.month,
                  scenario: str = "ACTUAL", date_from: str = "", date_to: str = "",
                  account_id: int | None = None, subtree: int = 0, tag_id: int | None = None,
                  payee_id: int | None = None, account_type: AccountTypeFilter | None = None,
                  level_id: int | None = None,
                  conn: Connection = Depends(get_connection)) -> dict:
    result = _run(conn, metric, dimension, scenario, date_from, date_to, account_id,
                  subtree, tag_id, payee_id, account_type, level_id)
    out = {
        **result, "metric": metric.value, "dimension": dimension.value,
        "scenario": scenario, "date_from": date_from, "date_to": date_to,
        "account_id": account_id, "subtree": subtree, "tag_id": tag_id,
        "payee_id": payee_id, "account_type": account_type.value if account_type else "",
        "level_id": level_id, "today": date.today().isoformat(),
    }
    if date_from and date_to:
        prev_from, prev_to, next_from, next_to = shift_range(date_from, date_to)
        out.update(prev_from=prev_from, prev_to=prev_to, next_from=next_from, next_to=next_to)
    return out


@router.get("/custom.csv")
def custom_report_csv(metric: Metric = Metric.net_amount, dimension: Dimension = Dimension.month,
                      scenario: str = "ACTUAL", date_from: str = "", date_to: str = "",
                      account_id: int | None = None, subtree: int = 0, tag_id: int | None = None,
                      payee_id: int | None = None, account_type: AccountTypeFilter | None = None,
                      level_id: int | None = None,
                      conn: Connection = Depends(get_connection)):
    result = _run(conn, metric, dimension, scenario, date_from, date_to, account_id,
                  subtree, tag_id, payee_id, account_type, level_id)
    return export.custom_report_csv(result, metric, dimension, scenario, date_from, date_to)


@router.get("/custom.xlsx")
def custom_report_xlsx(metric: Metric = Metric.net_amount, dimension: Dimension = Dimension.month,
                       scenario: str = "ACTUAL", date_from: str = "", date_to: str = "",
                       account_id: int | None = None, subtree: int = 0, tag_id: int | None = None,
                       payee_id: int | None = None, account_type: AccountTypeFilter | None = None,
                       level_id: int | None = None,
                       conn: Connection = Depends(get_connection)):
    result = _run(conn, metric, dimension, scenario, date_from, date_to, account_id,
                  subtree, tag_id, payee_id, account_type, level_id)
    return export.custom_report_xlsx(result, metric, dimension, scenario, date_from, date_to)
