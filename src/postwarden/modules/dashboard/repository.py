"""Raw SQL access for the dashboard module — the landing page's own five
queries, ported straight from `app/main.py`'s `dashboard()` route.
Forked rather than reused from `modules/reports/repository.py`'s own
`fn_trial_balance` call (REBUILD.md decision 3's "deletable on its own"
test, the same reasoning every other module's own `repository.py`
already gives for not importing another module's) even though the
trial-balance-totals query below hits the same Postgres function.

Every function takes `conn` as its first argument and returns plain
dicts/lists/`Decimal`s, same convention every other module's own
`repository.py` follows — nothing here decides anything beyond "here is
the row Postgres returned," that's `service.py`'s job.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection


def trial_balance_by_type(conn: Connection, scenario: str, as_of: str,
                           since: str | None = None) -> dict[str, Decimal]:
    """`fn_trial_balance(scenario, as_of, since)`'s rows, summed to one
    net per `acct_type` — `service.dashboard_summary` reads `asset`/
    `liability` off an unwindowed call for net worth, and `income`/
    `expense` off a `since=month_start` call for the month-to-date
    figures, matching legacy's own two separate `q()` calls
    (`as_of_rows`/`mtd_rows`)."""
    rows = conn.execute(
        text("SELECT acct_type, net FROM fn_trial_balance(:scenario, :as_of, :since)"),
        {"scenario": scenario, "as_of": as_of, "since": since},
    ).mappings()
    totals: dict[str, Decimal] = {}
    for r in rows:
        totals[r["acct_type"]] = totals.get(r["acct_type"], Decimal(0)) + r["net"]
    return totals


def recent_entries(conn: Connection, scenario: str, limit: int) -> list[dict]:
    """The most recent postings in `scenario`, newest first — ported
    from legacy's own `recent` query, unchanged."""
    rows = conn.execute(text("""
        SELECT e.id, e.entry_date, e.description, p.name AS payee_name,
               (SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_debits
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id
          LEFT JOIN payees p ON p.id = e.payee_id
         WHERE s.code = :scenario
         ORDER BY e.entry_date DESC, e.seq DESC
         LIMIT :limit
    """), {"scenario": scenario, "limit": limit}).mappings()
    return [dict(r) for r in rows]


def recent_entry_lines(conn: Connection, entry_ids: list[str]) -> list[dict]:
    """Every line on any of `entry_ids` — `service._flow_by_id` groups
    these by debit/credit side to build each recent entry's "X → Y"
    label. Caller guards the empty-list case, same convention
    `modules/staging/service.list_pending` already established for the
    identical shape."""
    rows = conn.execute(text("""
        SELECT l.entry_id, a.name AS account_name, l.debit, l.credit
          FROM journal_lines l
          JOIN accounts a ON a.id = l.account_id
         WHERE l.entry_id = ANY(:entry_ids)
    """), {"entry_ids": entry_ids}).mappings()
    return [dict(r) for r in rows]


def upcoming_schedules(conn: Connection, limit: int) -> list[dict]:
    """Every *active* schedule, soonest first — ported from legacy's own
    `upcoming` query, unchanged. Never includes one that's actually due
    today: `materialize_due_schedules` (the auth middleware, legacy and
    this rebuild alike) already turns a due occurrence into a real
    Staging entry and pushes `next_date` past today before this query
    ever runs, so every row here is a genuine future date."""
    rows = conn.execute(text("""
        SELECT se.id, se.next_date, se.description, p.name AS payee_name,
               (SELECT COALESCE(SUM(l.debit), 0) FROM scheduled_entry_lines l
                 WHERE l.scheduled_entry_id = se.id) AS total_debits
          FROM scheduled_entries se
          LEFT JOIN payees p ON p.id = se.payee_id
         WHERE se.is_active
         ORDER BY se.next_date, se.id
         LIMIT :limit
    """), {"limit": limit}).mappings()
    return [dict(r) for r in rows]


def upcoming_schedule_lines(conn: Connection, schedule_ids: list[int]) -> list[dict]:
    """Every line on any of `schedule_ids` — same shape/purpose as
    `recent_entry_lines` above, just against `scheduled_entry_lines`."""
    rows = conn.execute(text("""
        SELECT l.scheduled_entry_id, a.name AS account_name, l.debit, l.credit
          FROM scheduled_entry_lines l
          JOIN accounts a ON a.id = l.account_id
         WHERE l.scheduled_entry_id = ANY(:schedule_ids)
    """), {"schedule_ids": schedule_ids}).mappings()
    return [dict(r) for r in rows]
