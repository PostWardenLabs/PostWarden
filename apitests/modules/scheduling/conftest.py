"""Shared fixture book for `modules/scheduling/` tests. See
`../../conftest.py` for the `conn` fixture (real Postgres, rolled back
after every test) and the `mk_*` row-builder helpers this uses."""
import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_scenario


def mk_payee(conn, name: str) -> dict:
    row = conn.execute(
        text("INSERT INTO payees (name) VALUES (:name) RETURNING id, name"), {"name": name}
    ).mappings().one()
    return dict(row)


@pytest.fixture
def book(conn):
    """The Staging scenario plus an ACTUAL destination scenario, and
    Checking (asset) / Salary (income) accounts postable in both —
    everything `modules/scheduling/` tests need to create a schedule or
    template and, for schedules, materialize a due occurrence into
    Staging."""
    staging = mk_scenario(conn, "STAGING", is_staging=True)
    actual = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    payee = mk_payee(conn, "Employer Inc")
    return {"staging": staging, "actual": actual, "assets": assets, "checking": checking,
            "income": income, "salary": salary, "payee": payee}
