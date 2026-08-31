"""Assembly for the dashboard module — the landing page's five queries
(`repository.py`) rolled into one `dashboard_summary()` call.

One intentional omission: the pending-Staging count (the amber banner)
isn't computed here at all. The frontend's `useStagingPendingCount.ts`
reads `GET /staging`'s own `entries.length` instead, rather than this
module computing the identical count a second, independent way.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy.engine import Connection

from . import repository as repo

RECENT_LIMIT = 8
UPCOMING_LIMIT = 8

_NO_FLOW = {"debit_name": None, "credit_name": None}


def _flow_by_id(lines: list[dict], id_key: str) -> dict:
    """One `{row_id: {"debit_name", "credit_name"}}` map per side of the
    entries/schedules those `lines` belong to. This is a JSON API, so
    "more than one account on this side" comes back as `None` and the
    frontend decides how to render that rather than this module baking
    a display marker into the value itself."""
    debit_names: dict = {}
    credit_names: dict = {}
    for ln in lines:
        bucket = debit_names if ln["debit"] > 0 else credit_names
        bucket.setdefault(ln[id_key], set()).add(ln["account_name"])

    def one(names: set) -> str | None:
        return next(iter(names)) if len(names) == 1 else None

    return {
        row_id: {"debit_name": one(debit_names.get(row_id, set())),
                 "credit_name": one(credit_names.get(row_id, set()))}
        for row_id in set(debit_names) | set(credit_names)
    }


def dashboard_summary(conn: Connection) -> dict:
    today = date.today()
    today_iso = today.isoformat()
    month_start = today.replace(day=1).isoformat()

    as_of_totals = repo.trial_balance_by_type(conn, "ACTUAL", today_iso)
    net_worth = as_of_totals.get("asset", Decimal(0)) + as_of_totals.get("liability", Decimal(0))

    mtd_totals = repo.trial_balance_by_type(conn, "ACTUAL", today_iso, month_start)
    mtd_income = -mtd_totals.get("income", Decimal(0))
    mtd_expenses = mtd_totals.get("expense", Decimal(0))

    recent = repo.recent_entries(conn, "ACTUAL", RECENT_LIMIT)
    recent_ids = [r["id"] for r in recent]
    recent_flow = _flow_by_id(repo.recent_entry_lines(conn, recent_ids), "entry_id") if recent_ids else {}
    recent_out = [{**r, **recent_flow.get(r["id"], _NO_FLOW)} for r in recent]

    upcoming = repo.upcoming_schedules(conn, UPCOMING_LIMIT)
    upcoming_ids = [r["id"] for r in upcoming]
    upcoming_flow = (_flow_by_id(repo.upcoming_schedule_lines(conn, upcoming_ids), "scheduled_entry_id")
                      if upcoming_ids else {})
    upcoming_out = [{**r, **upcoming_flow.get(r["id"], _NO_FLOW)} for r in upcoming]

    return {
        "today": today_iso,
        "month_label": today.strftime("%B %Y"),
        "net_worth": net_worth,
        "mtd_income": mtd_income,
        "mtd_expenses": mtd_expenses,
        "mtd_net": mtd_income - mtd_expenses,
        "recent": recent_out,
        "upcoming": upcoming_out,
    }
