"""Shared fixture `book` for `analytics/` tests — forked from
`modules/reports/conftest.py`'s own fixture of the same name, not
imported (the "deletable on its own" test, same reasoning
`analytics/repository.py`'s own docstring already gives for
forking `reports`'/`reference`'s queries instead of reusing them).

Extended a little past the reports fixture's own minimal shape, since
this package's own tests need things that one never exercises: a second
scenario (so `/api/scenarios`' `entry_count` and `/api/entries`'
`scenario` filter both have something to distinguish), an
`account_levels` row a scenario's own `base_level_id` points at (so
`entry_count`/`base_level_name` are both non-trivial), and an inactive
account (so `analytics.repository.accounts`' own "no `is_active`
filter, unlike reports" behavior has something to actually prove)."""
import pytest
from sqlalchemy import text

from ..conftest import mk_account, mk_account_level, mk_entry, mk_line, mk_scenario


@pytest.fixture
def book(conn):
    """
        1000 Assets (summary)
          1100 Checking (leaf, is_cashflow)
        3000 Equity (summary)
          3100 Opening Balance Equity (leaf)
        4000 Income (summary)
          4100 Salary (leaf)
        5000 Expenses (summary)
          5100 Rent (leaf)
          5900 Old Expense (leaf, is_active = FALSE)

    Two scenarios: ACTUAL (base_level_id set, two entries) and BUDGET2
    (an income-statement-only-less plain scenario, no entries — proves
    `entry_count` can legitimately be zero).

    Entries (ACTUAL only), spanning two months so `/api/monthly-activity`
    groups into more than one row:
      2026-01-15  Opening balance   Dr Checking 1000 / Cr Opening Balance Equity 1000
      2026-02-01  Paycheck          Dr Checking 2000 / Cr Salary 2000
      2026-02-05  Rent payment      Dr Rent 800       / Cr Checking 800
    """
    level = mk_account_level(conn, "Top level", 1)
    scenario = mk_scenario(conn, "ACTUAL", base_level_id=level["id"])
    other_scenario = mk_scenario(conn, "BUDGET2", scenario_type="budget")

    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    equity = mk_account(conn, "3000", "Equity", "equity", is_postable=False)
    obe = mk_account(conn, "3100", "Opening Balance Equity", "equity", parent_id=equity["id"])
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    rent = mk_account(conn, "5100", "Rent", "expense", parent_id=expenses["id"])
    old_expense = mk_account(conn, "5900", "Old Expense", "expense", parent_id=expenses["id"])
    conn.execute(
        text("UPDATE accounts SET is_active = FALSE WHERE id = :id"),
        {"id": old_expense["id"]},
    )

    e1 = mk_entry(conn, scenario["id"], "2026-01-15", "Opening balance")
    mk_line(conn, e1, checking["id"], 1000, 1)
    mk_line(conn, e1, obe["id"], -1000, 2)

    e2 = mk_entry(conn, scenario["id"], "2026-02-01", "Paycheck")
    mk_line(conn, e2, checking["id"], 2000, 1)
    mk_line(conn, e2, salary["id"], -2000, 2)

    e3 = mk_entry(conn, scenario["id"], "2026-02-05", "Rent payment")
    mk_line(conn, e3, rent["id"], 800, 1)
    mk_line(conn, e3, checking["id"], -800, 2)

    return {
        "level": level, "scenario": scenario, "other_scenario": other_scenario,
        "assets": assets, "checking": checking, "equity": equity, "obe": obe,
        "income": income, "salary": salary, "expenses": expenses, "rent": rent,
        "old_expense": old_expense, "entries": [e1, e2, e3],
    }
