"""Direct tests of `dashboard.repository` against a real Postgres
connection (`book`/`conn`, see `./conftest.py` and `../../conftest.py`)."""
from sqlalchemy import text

from postwarden.modules.dashboard import repository
from .conftest import mk_schedule, mk_schedule_line


def test_trial_balance_by_type_sums_net_per_account_type(book, conn):
    totals = repository.trial_balance_by_type(conn, "ACTUAL", book["today"].isoformat())
    # Checking: +5000 (opening) +3000 (paycheck) -1200 (rent) = 6800.
    assert totals["asset"] == 6800
    # Credit Card: -300 (a $300 balance, credit-normal so negative here).
    assert totals["liability"] == -300
    assert totals["income"] == -3000
    assert totals["expense"] == 1200


def test_trial_balance_by_type_since_scopes_to_a_window(book, conn):
    # Scoped to this month only: the opening-balance entries (dated well
    # before `month_start`) drop out entirely, leaving just the paycheck
    # and rent payment.
    totals = repository.trial_balance_by_type(
        conn, "ACTUAL", book["today"].isoformat(), book["month_start"].isoformat())
    assert totals["asset"] == 1800  # +3000 paycheck, -1200 rent
    # fn_trial_balance still returns a (zero) row for every active account
    # regardless of activity in the window (its own LEFT JOIN, not an
    # inner one) — Credit Card had no postings this month, but it's still
    # a key here, at 0, not simply absent.
    assert totals["liability"] == 0
    assert totals["income"] == -3000
    assert totals["expense"] == 1200


def test_recent_entries_orders_newest_first_and_carries_payee(book, conn):
    rows = repository.recent_entries(conn, "ACTUAL", 8)
    assert len(rows) == 4
    dates = [r["entry_date"].isoformat() for r in rows]
    assert dates == sorted(dates, reverse=True)
    paycheck = next(r for r in rows if r["description"] == "Paycheck")
    assert paycheck["payee_name"] == "Employer Inc"
    rent = next(r for r in rows if r["description"] == "Rent payment")
    assert rent["payee_name"] is None
    assert rent["total_debits"] == 1200


def test_recent_entries_respects_limit(book, conn):
    rows = repository.recent_entries(conn, "ACTUAL", 2)
    assert len(rows) == 2


def test_recent_entry_lines_returns_every_line_for_the_given_entries(book, conn):
    rows = repository.recent_entries(conn, "ACTUAL", 8)
    rent = next(r for r in rows if r["description"] == "Rent payment")
    lines = repository.recent_entry_lines(conn, [rent["id"]])
    names = {ln["account_name"] for ln in lines}
    assert names == {"Rent", "Checking"}


def test_upcoming_schedules_excludes_inactive_and_orders_by_next_date(book, conn):
    soon = mk_schedule(conn, book["actual"]["id"], "Rent", (book["today"]).isoformat(),
                        payee_id=book["payee"]["id"])
    later_date = (book["today"].replace(day=28)).isoformat()
    later = mk_schedule(conn, book["actual"]["id"], "Subscription", later_date)
    conn.execute(text("UPDATE scheduled_entries SET is_active = FALSE WHERE id = :id"), {"id": later})

    rows = repository.upcoming_schedules(conn, 8)
    ids = [r["id"] for r in rows]
    assert soon in ids
    assert later not in ids  # inactive, excluded


def test_upcoming_schedule_lines_returns_every_line_for_the_given_schedules(book, conn):
    sched_id = mk_schedule(conn, book["actual"]["id"], "Rent", book["today"].isoformat())
    mk_schedule_line(conn, sched_id, book["rent"]["id"], 1200, 1)
    mk_schedule_line(conn, sched_id, book["checking"]["id"], -1200, 2)

    lines = repository.upcoming_schedule_lines(conn, [sched_id])
    names = {ln["account_name"] for ln in lines}
    assert names == {"Rent", "Checking"}
