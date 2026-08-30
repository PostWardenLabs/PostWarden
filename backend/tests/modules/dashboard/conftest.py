"""Shared fixture `book` for `modules/dashboard/` tests. See
`../../conftest.py` for the `conn` fixture (real Postgres, rolled back
after every test) and the `mk_*` row-builder helpers this uses.

Every date below is relative to `date.today()`, not a hardcoded
literal — the same convention `modules/scheduling/test_service.py`
already established, since "this month" is exactly what this module's
own month-to-date figures depend on and a literal date would eventually
fall in the wrong month."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_entry, mk_line, mk_scenario


def mk_payee(conn, name: str) -> dict:
    row = conn.execute(
        text("INSERT INTO payees (name) VALUES (:name) RETURNING id, name"), {"name": name}
    ).mappings().one()
    return dict(row)


def mk_schedule(conn, target_scenario_id: int, description: str, next_date: str, *,
                payee_id: int | None = None) -> int:
    row = conn.execute(text("""
        INSERT INTO scheduled_entries (description, target_scenario_id, interval_unit, next_date, payee_id)
        VALUES (:description, :target_scenario_id, 'month', :next_date, :payee_id)
        RETURNING id
    """), {"description": description, "target_scenario_id": target_scenario_id,
            "next_date": next_date, "payee_id": payee_id}).mappings().one()
    return row["id"]


def mk_schedule_line(conn, scheduled_entry_id: int, account_id: int, amount, line_no: int) -> None:
    conn.execute(text("""
        INSERT INTO scheduled_entry_lines (scheduled_entry_id, line_no, account_id, amount)
        VALUES (:scheduled_entry_id, :line_no, :account_id, :amount)
    """), {"scheduled_entry_id": scheduled_entry_id, "account_id": account_id,
            "amount": amount, "line_no": line_no})


@pytest.fixture
def book(conn):
    """
        1000 Assets (summary)
          1100 Checking (leaf)
        2000 Liabilities (summary)
          2100 Credit Card (leaf)
        3000 Equity (summary)
          3100 Opening Balance Equity (leaf)
        4000 Income (summary)
          4100 Salary (leaf)
        5000 Expenses (summary)
          5100 Rent (leaf)

    ACTUAL only. Two entries dated well before this month establish
    opening balances (Checking 5000 dr / Opening Balance Equity 5000 cr;
    Opening Balance Equity 300 dr / Credit Card 300 cr — a $300 credit
    card balance), so `net_worth` has a real liability to net against an
    asset. Two more, dated *this* month (the 1st, and today), are the
    only ones `dashboard_summary`'s own `since=month_start` window
    should ever count:
      month start  Paycheck       Dr Checking 3000 / Cr Salary 3000
      today        Rent payment   Dr Rent 1200      / Cr Checking 1200
    """
    today = date.today()
    month_start = today.replace(day=1)
    long_ago = month_start - timedelta(days=400)

    actual = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    liabilities = mk_account(conn, "2000", "Liabilities", "liability", is_postable=False)
    credit_card = mk_account(conn, "2100", "Credit Card", "liability", parent_id=liabilities["id"])
    equity = mk_account(conn, "3000", "Equity", "equity", is_postable=False)
    obe = mk_account(conn, "3100", "Opening Balance Equity", "equity", parent_id=equity["id"])
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    rent = mk_account(conn, "5100", "Rent", "expense", parent_id=expenses["id"])
    payee = mk_payee(conn, "Employer Inc")

    e1 = mk_entry(conn, actual["id"], long_ago.isoformat(), "Opening balance")
    mk_line(conn, e1, checking["id"], 5000, 1)
    mk_line(conn, e1, obe["id"], -5000, 2)

    e2 = mk_entry(conn, actual["id"], long_ago.isoformat(), "Opening credit card balance")
    mk_line(conn, e2, obe["id"], 300, 1)
    mk_line(conn, e2, credit_card["id"], -300, 2)

    e3 = mk_entry(conn, actual["id"], month_start.isoformat(), "Paycheck", payee_id=payee["id"])
    mk_line(conn, e3, checking["id"], 3000, 1)
    mk_line(conn, e3, salary["id"], -3000, 2)

    e4 = mk_entry(conn, actual["id"], today.isoformat(), "Rent payment")
    mk_line(conn, e4, rent["id"], 1200, 1)
    mk_line(conn, e4, checking["id"], -1200, 2)

    return {
        "actual": actual, "assets": assets, "checking": checking, "liabilities": liabilities,
        "credit_card": credit_card, "equity": equity, "obe": obe, "income": income, "salary": salary,
        "expenses": expenses, "rent": rent, "payee": payee,
        "today": today, "month_start": month_start, "long_ago": long_ago,
        "entries": [e1, e2, e3, e4],
    }
