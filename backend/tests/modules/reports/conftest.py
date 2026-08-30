"""Shared fixture book for `modules/reports/` tests — one small,
hand-computable chart of accounts + a few balanced entries in the
ACTUAL scenario, reused across `test_repository.py`/`test_service.py`/
`test_router.py` so each file doesn't reinvent it. See `../../conftest.py`
for the `conn` fixture (real Postgres, rolled back after every test) and
the `mk_*` row-builder helpers this uses.
"""
import pytest

from ...conftest import mk_account, mk_entry, mk_line, mk_scenario


@pytest.fixture
def book(conn):
    """A minimal, hand-computable ACTUAL-scenario book:

        1000 Assets (summary)
          1100 Checking (leaf, is_cashflow)
        3000 Equity (summary)
          3100 Opening Balance Equity (leaf)
        4000 Income (summary)
          4100 Salary (leaf)
        5000 Expenses (summary)
          5100 Rent (leaf)

    Three balanced entries:
      2026-01-15  Opening balance   Dr Checking 1000 / Cr Opening Balance Equity 1000
      2026-02-01  Paycheck          Dr Checking 2000 / Cr Salary 2000
      2026-02-05  Rent payment      Dr Rent 800       / Cr Checking 800

    Every number asserted against in this package's tests is hand-
    derived from exactly these three entries — see each test's own
    comment for the arithmetic. `entry_date`s deliberately span two
    months (Jan/Feb 2026) so month-to-date vs. fiscal-year-to-date vs.
    all-time actually differ, the same three-way split Trial Balance's
    synthetic earnings rows depend on."""
    scenario = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    equity = mk_account(conn, "3000", "Equity", "equity", is_postable=False)
    obe = mk_account(conn, "3100", "Opening Balance Equity", "equity", parent_id=equity["id"])
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    rent = mk_account(conn, "5100", "Rent", "expense", parent_id=expenses["id"])

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
        "scenario": scenario, "assets": assets, "checking": checking, "equity": equity, "obe": obe,
        "income": income, "salary": salary, "expenses": expenses, "rent": rent,
        "entries": [e1, e2, e3],
    }
