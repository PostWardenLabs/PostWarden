"""Shared fixture book for `modules/entries/` tests — a scenario and a
couple of postable accounts, enough to post/reverse/edit entries by hand.
See `../../conftest.py` for the `conn` fixture (real Postgres, rolled
back after every test) and the `mk_*` row-builder helpers this uses.
"""
import pytest

from ...conftest import mk_account, mk_entry, mk_line, mk_scenario


@pytest.fixture
def book(conn):
    """One ACTUAL scenario (balance-enforced, the default `mk_scenario`
    gives), Checking (asset) and Salary (income), each under its own
    non-postable summary parent — the same shape `modules/reports/`'s
    own `book` fixture uses, trimmed to what entries tests need."""
    scenario = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    return {"scenario": scenario, "assets": assets, "checking": checking,
            "income": income, "salary": salary}


@pytest.fixture
def posted_entry(conn, book):
    """One already-posted, balanced entry — Dr Checking 500 / Cr Salary
    500 — for tests that reverse or edit something rather than create
    it. Built directly via `mk_entry`/`mk_line` (bypassing
    `service.create_entry`) same as `modules/reports/`'s `book` fixture
    does, since these rows just need to already exist, not be created
    through the code under test."""
    entry_id = mk_entry(conn, book["scenario"]["id"], "2026-03-01", "Paycheck")
    mk_line(conn, entry_id, book["checking"]["id"], 500, 1)
    mk_line(conn, entry_id, book["salary"]["id"], -500, 2)
    return entry_id
