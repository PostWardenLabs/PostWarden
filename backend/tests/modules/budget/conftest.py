"""Shared fixture book for `modules/budget/` tests — a small, hand-
computable chart of income/expense accounts plus one asset account to
balance ACTUAL postings against, reused across `test_repository.py`/
`test_service.py`/`test_router.py`. See `../../conftest.py` for the
`conn` fixture (real Postgres, rolled back after every test) and the
`mk_*` row-builder helpers this uses.
"""
import pytest

from ...conftest import mk_account, mk_budget_line, mk_entry, mk_line, mk_scenario


@pytest.fixture
def book(conn):
    """Two scenarios and a hand-computable chart:

        1000 Checking (asset, leaf, is_cashflow) — ACTUAL's counter-account
        5000 Expenses (summary)
          5100 Rent (leaf)
        5200 Other (summary)
          5210 Gas (leaf)
          5220 Electric (leaf)

    ACTUAL: one August 2026 entry, Dr Rent 450 / Cr Checking 450.
    BUD (income-statement-only): Rent budgeted 600 for 2026-08; also
    600/300/300 across May/June/July (the 3 calendar months before
    August) so avg3_scenario has a hand-checkable answer (600+300+300)/3
    = 400; and 300 for July alone so the "last month" quickfill figure is
    checkable too. Gas/Electric (5210/5220, under the summary 5200)
    budgeted 300/200 for August, so the rollup onto 5200 is checkable
    (500) with no ACTUAL postings against either — Actual should read 0,
    not error, for an account with no activity at all."""
    actual = mk_scenario(conn, "ACTUAL")
    bud = mk_scenario(conn, "BUD", scenario_type="budget", income_statement_only=True)

    checking = mk_account(conn, "1000", "Checking", "asset", is_cashflow=True)
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    rent = mk_account(conn, "5100", "Rent", "expense", parent_id=expenses["id"])
    other = mk_account(conn, "5200", "Other", "expense", is_postable=False)
    gas = mk_account(conn, "5210", "Gas", "expense", parent_id=other["id"])
    electric = mk_account(conn, "5220", "Electric", "expense", parent_id=other["id"])

    e1 = mk_entry(conn, actual["id"], "2026-08-05", "Rent payment")
    mk_line(conn, e1, rent["id"], 450, 1)
    mk_line(conn, e1, checking["id"], -450, 2)

    mk_budget_line(conn, bud["id"], rent["id"], 600, period_month="2026-08-01")
    mk_budget_line(conn, bud["id"], rent["id"], 300, period_month="2026-07-01")
    mk_budget_line(conn, bud["id"], rent["id"], 300, period_month="2026-06-01")
    mk_budget_line(conn, bud["id"], rent["id"], 600, period_month="2026-05-01")
    mk_budget_line(conn, bud["id"], gas["id"], 300, period_month="2026-08-01")
    mk_budget_line(conn, bud["id"], electric["id"], 200, period_month="2026-08-01")

    return {
        "actual": actual, "bud": bud, "checking": checking, "expenses": expenses,
        "rent": rent, "other": other, "gas": gas, "electric": electric,
    }
