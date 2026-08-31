"""The custom-reports logic: validate every filter against a real row,
resolve the `account_level` dimension's `level_id` to a depth, decide
which filters actually apply, then hand `repository.py` a fully-vetted
config. The enum membership itself is already guaranteed before this
runs — `Metric`/`Dimension`/`AccountTypeFilter` are the route
signature's own types, so FastAPI 422s anything else — which leaves
this file exactly the checks a type system can't do: does this id name
a real row, is this date a date, does this dimension have what it
needs.

Raises `ValueError` with a user-facing message on every failed check —
`router.py` converts to a 400, the same division `modules/reference/`
uses.
"""
from datetime import date

from sqlalchemy.engine import Connection

from . import repository
from .enums import AccountTypeFilter, Dimension, Metric


def _checked_date(value: str, name: str) -> str | None:
    """Blank means unbounded (a custom report over all history is a
    sensible default view — deliberately *not* the "blank means this
    month" defaulting the Income Statement GET applies); non-blank must
    be a real ISO date, refused here as a 400 rather than surfacing as
    a Postgres error 500 later."""
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date") from None
    return value


def run(conn: Connection, *, metric: Metric, dimension: Dimension, scenario: str,
        date_from: str, date_to: str, account_id: int | None, subtree: bool,
        tag_id: int | None, payee_id: int | None,
        account_type: AccountTypeFilter | None, level_id: int | None) -> dict:
    """Validate, then run: the grouped rows plus the independently
    computed ungrouped total (see `repository.run_total` for why it
    isn't just the rows summed)."""
    date_from = _checked_date(date_from, "date_from")
    date_to = _checked_date(date_to, "date_to")

    # Grouping by scenario is *comparing* scenarios, so the scenario
    # filter (which would collapse the report to a single row) is
    # dropped for that dimension rather than rejected — the config a
    # user reaches by flipping the dimension dropdown should keep
    # working, not 400 over a filter another dimension needed.
    scenario_filter = None if dimension is Dimension.scenario else scenario
    if scenario_filter and not repository.scenario_exists(conn, scenario_filter):
        raise ValueError(f"Unknown scenario {scenario_filter!r}")

    if account_id is not None and not repository.account_exists(conn, account_id):
        raise ValueError(f"Account #{account_id} not found")
    if tag_id is not None and not repository.tag_exists(conn, tag_id):
        raise ValueError(f"Tag #{tag_id} not found")
    if payee_id is not None and not repository.payee_exists(conn, payee_id):
        raise ValueError(f"Payee #{payee_id} not found")

    level_depth = None
    if dimension is Dimension.account_level:
        if level_id is None:
            raise ValueError("The account level dimension needs a level_id")
        level_depth = repository.account_level_depth(conn, level_id)
        if level_depth is None:
            raise ValueError(f"Level #{level_id} not found")

    filters = dict(scenario=scenario_filter, date_from=date_from, date_to=date_to,
                   account_id=account_id, subtree=subtree, tag_id=tag_id, payee_id=payee_id,
                   account_type=account_type.value if account_type else None)
    rows = repository.run_report(conn, metric, dimension, level_depth=level_depth, **filters)
    total = repository.run_total(conn, metric, **filters)
    return {"rows": rows, "total": total, "row_count": len(rows)}
