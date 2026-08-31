"""Shared fixture book for `modules/custom_reports/` tests — its own
small, hand-computable book rather than reusing `modules/reports/`'s
(sibling test packages fork fixtures the same way sibling modules fork
helpers), and deliberately wider than that one in exactly the ways this
module's filters need: two scenarios, tags (overlapping on one entry),
a payee, and an `account_levels` row for the `account_level` dimension.
See `../../conftest.py` for the `conn` fixture (real Postgres, rolled
back after every test) and the `mk_*` row-builder helpers.
"""
import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_account_level, mk_entry, mk_line, mk_scenario


def mk_tag(conn, name: str) -> int:
    row = conn.execute(text("INSERT INTO tags (name) VALUES (:name) RETURNING id"),
                       {"name": name}).mappings().one()
    return row["id"]


def mk_payee(conn, name: str) -> int:
    row = conn.execute(text("INSERT INTO payees (name) VALUES (:name) RETURNING id"),
                       {"name": name}).mappings().one()
    return row["id"]


def tag_entry(conn, entry_id: str, tag_id: int) -> None:
    conn.execute(text("INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (:e, :t)"),
                 {"e": entry_id, "t": tag_id})


@pytest.fixture
def book(conn):
    """A minimal book exercising every filter and dimension:

        1000 Assets (summary)
          1100 Checking (leaf)
        4000 Income (summary)
          4100 Salary (leaf)
        5000 Expenses (summary)
          5100 Dining (leaf)
          5200 Groceries (leaf)

    ACTUAL-scenario entries:
      e1 2026-01-10  Cafe lunch      Dr Dining 100    / Cr Checking   payee=Cafe  tags=[fun]
      e2 2026-01-20  Groceries run   Dr Groceries 250 / Cr Checking               tags=[fun, food]
      e3 2026-02-05  Cafe dinner     Dr Dining 60     / Cr Checking   payee=Cafe
      e4 2026-02-01  Paycheck        Dr Checking 2000 / Cr Salary

    PLAN-scenario (what_if) entry:
      e5 2026-01-15  Planned dining  Dr Dining 80     / Cr Checking

    Hand-derived numbers every test in this package asserts against
    (`net_amount` unless said otherwise, expense-filtered where noted):
      - by month, expenses, ACTUAL:   2026-01 → 350, 2026-02 → 60; total 410
      - by account, expenses, ACTUAL: Dining 160, Groceries 250
      - by tag, expenses, ACTUAL:     food 250, fun 350 (e2 carries both
        tags, so rows sum to 600 > the 410 total — the documented
        overlapping-tags property)
      - by scenario, expenses:        ACTUAL 410, PLAN 80
      - by account_level depth 1, expenses, ACTUAL: Expenses 410
      - Salary's net_amount sign-flips to +2000 (credit-normal)
      - entry_count by month, ACTUAL: 2 and 2, total 4 (distinct)
    """
    level = mk_account_level(conn, "Top", 1)
    actual = mk_scenario(conn, "ACTUAL")
    plan = mk_scenario(conn, "PLAN", scenario_type="what_if")

    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    dining = mk_account(conn, "5100", "Dining", "expense", parent_id=expenses["id"])
    groceries = mk_account(conn, "5200", "Groceries", "expense", parent_id=expenses["id"])

    cafe = mk_payee(conn, "Cafe")
    fun = mk_tag(conn, "fun")
    food = mk_tag(conn, "food")

    e1 = mk_entry(conn, actual["id"], "2026-01-10", "Cafe lunch", payee_id=cafe)
    mk_line(conn, e1, dining["id"], 100, 1)
    mk_line(conn, e1, checking["id"], -100, 2)
    tag_entry(conn, e1, fun)

    e2 = mk_entry(conn, actual["id"], "2026-01-20", "Groceries run")
    mk_line(conn, e2, groceries["id"], 250, 1)
    mk_line(conn, e2, checking["id"], -250, 2)
    tag_entry(conn, e2, fun)
    tag_entry(conn, e2, food)

    e3 = mk_entry(conn, actual["id"], "2026-02-05", "Cafe dinner", payee_id=cafe)
    mk_line(conn, e3, dining["id"], 60, 1)
    mk_line(conn, e3, checking["id"], -60, 2)

    e4 = mk_entry(conn, actual["id"], "2026-02-01", "Paycheck")
    mk_line(conn, e4, checking["id"], 2000, 1)
    mk_line(conn, e4, salary["id"], -2000, 2)

    e5 = mk_entry(conn, plan["id"], "2026-01-15", "Planned dining")
    mk_line(conn, e5, dining["id"], 80, 1)
    mk_line(conn, e5, checking["id"], -80, 2)

    return {
        "level": level, "actual": actual, "plan": plan,
        "assets": assets, "checking": checking, "income": income, "salary": salary,
        "expenses": expenses, "dining": dining, "groceries": groceries,
        "cafe": cafe, "fun": fun, "food": food,
        "entries": [e1, e2, e3, e4, e5],
    }
