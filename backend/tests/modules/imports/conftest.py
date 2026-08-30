"""Shared fixture book for `modules/imports/` tests. See `../../conftest.py`
for the `conn` fixture (real Postgres, rolled back after every test) and
the `mk_*` row-builder helpers this uses."""
import pytest

from ...conftest import mk_account, mk_scenario


@pytest.fixture
def book(conn):
    """The Staging scenario plus an ACTUAL destination scenario, and
    Checking (asset) / Salary (income) / Rent (expense) accounts postable
    in both — everything `modules/imports/` tests need to stage a plain
    double-entry CSV or a mapped single-entry one. Rent is the third
    account (unlike `modules/staging/`'s own two-account book) because the
    mapped importer needs a real Category-side account distinct from the
    Account-side (money) one."""
    staging = mk_scenario(conn, "STAGING", is_staging=True)
    actual = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    expenses = mk_account(conn, "5000", "Expenses", "expense", is_postable=False)
    rent = mk_account(conn, "5100", "Rent", "expense", parent_id=expenses["id"])
    return {"staging": staging, "actual": actual, "assets": assets, "checking": checking,
            "income": income, "salary": salary, "expenses": expenses, "rent": rent}
