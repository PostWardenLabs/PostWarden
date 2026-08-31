"""Shared fixture book for `modules/reference/` tests. See
`../../conftest.py` for the `conn` fixture (real Postgres, rolled back
after every test) and the `mk_*` row-builder helpers this uses."""
import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_account_level, mk_entry, mk_line, mk_scenario


def mk_payee(conn, name: str) -> dict:
    row = conn.execute(
        text("INSERT INTO payees (name) VALUES (:name) RETURNING id, name"), {"name": name}
    ).mappings().one()
    return dict(row)


def mk_tag(conn, name: str) -> dict:
    row = conn.execute(
        text("INSERT INTO tags (name) VALUES (:name) RETURNING id, name"), {"name": name}
    ).mappings().one()
    return dict(row)


def attach_tag(conn, entry_id: str, tag_id: int) -> None:
    conn.execute(text("""
        INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (:entry_id, :tag_id)
    """), {"entry_id": entry_id, "tag_id": tag_id})


@pytest.fixture
def book(conn):
    """One account level, one scenario, a small two-account chart, two
    payees and two tags (each pair mergeable), and two posted entries —
    one carrying the first payee/tag of each pair (`acme`/`food`, the
    survivor every merge test below keeps), one carrying the second
    (`other`/`urgent`, the one every merge test folds away) — so a merge
    test can assert a real repointed-entry count (1), not just "didn't
    error." Enough for every list/create/toggle/rename/delete/merge test
    in this module."""
    level = mk_account_level(conn, "Category", 1)
    actual = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])

    acme = mk_payee(conn, "Acme")
    other = mk_payee(conn, "Other Co")
    food = mk_tag(conn, "food")
    urgent = mk_tag(conn, "urgent")

    e1 = mk_entry(conn, actual["id"], "2026-08-05", "Paycheck", payee_id=acme["id"])
    mk_line(conn, e1, checking["id"], 100, 1)
    mk_line(conn, e1, salary["id"], -100, 2)
    attach_tag(conn, e1, food["id"])

    e2 = mk_entry(conn, actual["id"], "2026-08-06", "Side gig", payee_id=other["id"])
    mk_line(conn, e2, checking["id"], 50, 1)
    mk_line(conn, e2, salary["id"], -50, 2)
    attach_tag(conn, e2, urgent["id"])

    return {
        "level": level, "actual": actual, "assets": assets, "checking": checking,
        "income": income, "salary": salary, "acme": acme, "other": other,
        "food": food, "urgent": urgent, "entry_id": e1, "other_entry_id": e2,
    }
