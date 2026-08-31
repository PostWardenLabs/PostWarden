"""Raw SQL access for the budget module — the ActualBudget-style grid for
an income-statement-only scenario (`scenarios.income_statement_only`).
Ported from `app/main.py`'s inline queries inside `_budget_rows`/
`save_budget_cell`. Same conventions `modules/reports/repository.py`/
`modules/entries/repository.py` already established: every function takes
a SQLAlchemy `Connection` (from `db.get_connection()`) and returns plain
dicts/scalars, `Decimal` for every money value, never `float`.

**`dim_accounts`, `account_balances`, `income_statement_only_scenario`
fork the equivalent queries already in `modules/reports/repository.py`
rather than importing them** — the same "a module should be deletable on
its own" test (`REBUILD.md` decision 3) `modules/staging/repository.py`'s
own docstring already applied when it forked `modules/entries/`'s filter
builder. `budget_line_amounts` and `budget_line_avg3` have no reports
equivalent at all: `reports.repository.budget_line_totals` sums
`budget_lines.amount` over an arbitrary date *range* (Income Statement's
Compare column needs one number for however many months the report spans)
while the Budget grid always wants exactly one calendar month's own
figure, or a 3-calendar-month average ending the month before — a
different query, not a narrowing of the same one.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection


def dim_accounts(conn: Connection) -> list[dict]:
    """Every active income/expense account, parent-before-child ordered —
    the Budget grid is income-statement-only by definition (a budget line
    can only ever target an income or expense account, per `db/schema.sql`'s
    `fn_budget_line_guard`), so unlike `reports.repository.dim_accounts`
    this never takes an `income_expense_only` toggle; it's always true."""
    rows = conn.execute(text("""
        SELECT * FROM v_dim_account
         WHERE is_active AND account_type IN ('income', 'expense')
         ORDER BY sort_path
    """)).mappings()
    return [dict(r) for r in rows]


def income_statement_only_scenario(conn: Connection, code: str) -> dict | None:
    """`id` for `code`, but only if it's actually income-statement-only —
    `None` both for an unknown code and for a real scenario that isn't
    (same single query legacy's own `_budget_rows` used, folding the type
    check into the `WHERE` rather than checking it after the fact). The
    caller (`service.budget_grid`) treats `None` as "nothing budgeted yet
    for this month" and returns the zero-figure stub, same as legacy's
    `budget_page` route did before ever calling `_budget_rows`."""
    row = conn.execute(text(
        "SELECT id FROM scenarios WHERE code = :code AND income_statement_only"
    ), {"code": code}).mappings().first()
    return dict(row) if row else None


def account_balances(conn: Connection, scenario: str, as_of: str, since: str) -> dict[int, Decimal]:
    """`fn_account_balances(scenario, as_of, since)` as an `{account_id:
    net}` map — the Budget grid's own Actual column (this calendar
    month's real postings) and, called again with a shifted window, its
    quickfill menu's "last month"/"3-month average" figures. Forked from
    `reports.repository.account_balances`, same query — see this module's
    own docstring for why forked rather than imported."""
    rows = conn.execute(
        text("SELECT * FROM fn_account_balances(:scenario, :as_of, :since)"),
        {"scenario": scenario, "as_of": as_of, "since": since},
    ).mappings()
    return {r["account_id"]: r["net"] for r in rows}


def budget_line_amounts(conn: Connection, scenario_id: int, period_month) -> dict[int, Decimal]:
    """`{account_id: amount}` for one income-statement-only scenario, one
    exact calendar month — the grid's own Budgeted column, and, called
    again against the prior month, the quickfill menu's "last month"
    figure."""
    rows = conn.execute(text("""
        SELECT account_id, amount FROM budget_lines
         WHERE scenario_id = :scenario_id AND period_month = :period_month
    """), {"scenario_id": scenario_id, "period_month": period_month}).mappings()
    return {r["account_id"]: r["amount"] for r in rows}


def budget_line_avg3(conn: Connection, scenario_id: int, three_month_start, month_start) -> dict[int, Decimal]:
    """`{account_id: sum(amount) / 3}` across the 3 calendar months
    immediately before `month_start` (`[three_month_start, month_start)`)
    — the quickfill menu's "3 month average of this scenario" figure.
    Division by the fixed 3 (not `COUNT(*)`) matches Income Statement
    Split's own Average column convention (`SPEC.md` decision 19's
    addendum): a quiet month with no budget line at all still counts as a
    zero in the denominator, it just never contributes a row here."""
    rows = conn.execute(text("""
        SELECT account_id, SUM(amount) AS total FROM budget_lines
         WHERE scenario_id = :scenario_id
           AND period_month >= :three_month_start AND period_month < :month_start
         GROUP BY account_id
    """), {"scenario_id": scenario_id, "three_month_start": three_month_start,
           "month_start": month_start}).mappings()
    return {r["account_id"]: r["total"] / 3 for r in rows}


def account_id_by_code(conn: Connection, code: str) -> int | None:
    """`save_budget_cell`'s own account-code -> id lookup — ported from
    `save_budget_cell`'s inline `q1("SELECT id FROM accounts WHERE code =
    %s", ...)`. A separate, narrower query from `modules.entries.
    repository.account_ids_by_code` (plural, batch) since a budget cell
    edit is always exactly one account at a time."""
    row = conn.execute(
        text("SELECT id FROM accounts WHERE code = :code"), {"code": code}
    ).mappings().first()
    return row["id"] if row else None


def upsert_budget_cell(conn: Connection, scenario_id: int, account_id: int, period_month,
                        amount: Decimal) -> None:
    """One cell of the grid, straight UPSERT — ported from `save_budget_
    cell`'s own `INSERT ... ON CONFLICT (scenario_id, account_id,
    period_month) DO UPDATE`. Unlike `journal_lines`, a budget line has no
    audit-trail reason to be append-only (`db/schema.sql`'s own comment on
    `budget_lines`): it's a working assumption, not a posted transaction,
    so overwriting in place is the right behavior, not a workaround.
    `fn_budget_line_guard` (BEFORE INSERT OR UPDATE, not deferred — unlike
    `journal_entries`' balance trigger) validates the scenario/account and
    raises immediately if either is wrong, so a caller's own `try/except`
    around this call catches it directly; no `SET CONSTRAINTS ALL
    IMMEDIATE` dance like `modules.entries.repository.check_deferred_
    constraints` needs."""
    conn.execute(text("""
        INSERT INTO budget_lines (scenario_id, account_id, period_month, amount)
        VALUES (:scenario_id, :account_id, :period_month, :amount)
        ON CONFLICT (scenario_id, account_id, period_month)
            DO UPDATE SET amount = EXCLUDED.amount
    """), {"scenario_id": scenario_id, "account_id": account_id,
           "period_month": period_month, "amount": amount})
