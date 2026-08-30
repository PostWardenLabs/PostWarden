"""Shared fixture book for `modules/staging/` tests. See `../../conftest.py`
for the `conn` fixture (real Postgres, rolled back after every test) and
the `mk_*` row-builder helpers this uses."""
import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_entry, mk_line, mk_scenario


def mk_schedule(conn, target_scenario_id: int, description: str = "Rent") -> int:
    """A minimal `scheduled_entries` row — just enough to be a valid
    `scheduled_entry_id` foreign key for a staged `journal_entries` row
    (`fn_staging_manual_entry_guard` requires one). No `scheduled_entry_
    lines`/tags: nothing under test here reads those, only the header's
    own `target_scenario_id`/`description`."""
    row = conn.execute(text("""
        INSERT INTO scheduled_entries (description, target_scenario_id, interval_unit, next_date)
        VALUES (:description, :target_scenario_id, 'month', CURRENT_DATE)
        RETURNING id
    """), {"description": description, "target_scenario_id": target_scenario_id}).mappings().one()
    return row["id"]


@pytest.fixture
def book(conn):
    """The Staging scenario plus an ACTUAL destination scenario, and
    Checking (asset) / Salary (income) accounts postable in both —
    everything `modules/staging/` tests need to stage, approve, reject,
    or edit an entry."""
    staging = mk_scenario(conn, "STAGING", is_staging=True)
    actual = mk_scenario(conn, "ACTUAL")
    assets = mk_account(conn, "1000", "Assets", "asset", is_postable=False)
    checking = mk_account(conn, "1100", "Checking", "asset", parent_id=assets["id"], is_cashflow=True)
    income = mk_account(conn, "4000", "Income", "income", is_postable=False)
    salary = mk_account(conn, "4100", "Salary", "income", parent_id=income["id"])
    return {"staging": staging, "actual": actual, "assets": assets, "checking": checking,
            "income": income, "salary": salary}


@pytest.fixture
def staged_entry(conn, book):
    """One pending, schedule-sourced staged entry — Dr Checking 500 / Cr
    Salary 500, headed for ACTUAL once approved. Built directly via
    `mk_schedule`/`mk_entry`/`mk_line` (bypassing `service.approve_entry`
    entirely), same "these rows just need to already exist" reasoning
    `modules/entries/conftest.py`'s own `posted_entry` fixture gives."""
    sched_id = mk_schedule(conn, book["actual"]["id"])
    entry_id = mk_entry(conn, book["staging"]["id"], "2026-03-01", "Paycheck",
                         scheduled_entry_id=sched_id)
    mk_line(conn, entry_id, book["checking"]["id"], 500, 1)
    mk_line(conn, entry_id, book["salary"]["id"], -500, 2)
    return entry_id
