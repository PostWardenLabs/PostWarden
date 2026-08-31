"""DB-backed tests for `modules/scheduling/repository.py` — mostly SQL
wiring (and, for `check_deferred_constraints`, the same deferred-trigger
interaction `modules/entries/repository.py`'s own test file already
covers for the Journal's own write path) against a real Postgres. Not
exhaustive: validation and end-to-end assembly behavior are covered by
test_service.py/test_router.py instead — this file just proves each
function returns/does what its own docstring says."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from postwarden.modules.scheduling import repository as repo


def test_account_ids_by_code_returns_only_what_exists(book, conn):
    found = repo.account_ids_by_code(conn, ["1100", "4100", "9999"])
    assert found == {"1100": book["checking"]["id"], "4100": book["salary"]["id"]}


def test_staging_scenario_id_finds_the_one_flagged_scenario(book, conn):
    assert repo.staging_scenario_id(conn) == book["staging"]["id"]


def test_staging_scenario_id_none_when_no_staging_scenario_exists(conn):
    assert repo.staging_scenario_id(conn) is None


def test_sync_tags_replaces_and_reactivates(book, conn):
    sched_id = repo.insert_schedule(
        conn, description="Rent", reference=None, payee_id=None,
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=date(2026, 9, 1))
    repo.sync_tags(conn, "scheduled_entry_tags", "scheduled_entry_id", sched_id, ["rent", "monthly"])
    assert set(repo.schedule_tag_names(conn, sched_id)) == {"rent", "monthly"}
    # Full replace, not additive: "monthly" drops off, "fixed" is new.
    repo.sync_tags(conn, "scheduled_entry_tags", "scheduled_entry_id", sched_id, ["rent", "fixed"])
    assert set(repo.schedule_tag_names(conn, sched_id)) == {"rent", "fixed"}
    # An archived tag comes back active once re-attached.
    conn.execute(text("UPDATE tags SET is_active = FALSE WHERE name = 'fixed'"))
    repo.sync_tags(conn, "scheduled_entry_tags", "scheduled_entry_id", sched_id, ["fixed"])
    row = conn.execute(text("SELECT is_active FROM tags WHERE name = 'fixed'")).mappings().one()
    assert row["is_active"] is True


def test_sync_journal_entry_tags_is_sync_tags_against_journal_entry_tags(book, conn):
    entry_id = repo.insert_staged_occurrence(
        conn, scenario_id=book["staging"]["id"], entry_date="2026-09-01", description="Rent",
        reference=None, payee_id=None, scheduled_entry_id=_mk_bare_schedule(conn, book))
    repo.sync_journal_entry_tags(conn, entry_id, ["rent"])
    row = conn.execute(text("""
        SELECT tg.name FROM journal_entry_tags jet JOIN tags tg ON tg.id = jet.tag_id
         WHERE jet.entry_id = :id
    """), {"id": entry_id}).mappings().one()
    assert row["name"] == "rent"


def _mk_bare_schedule(conn, book, next_date: date = date(2026, 9, 1)) -> int:
    return repo.insert_schedule(
        conn, description="Rent", reference=None, payee_id=None,
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=next_date)


def test_insert_schedule_and_line_round_trip(book, conn):
    sched_id = repo.insert_schedule(
        conn, description="Rent", reference="REF-1", payee_id=book["payee"]["id"],
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=date(2026, 9, 1))
    repo.insert_schedule_line(conn, scheduled_entry_id=sched_id, line_no=1,
                               account_id=book["checking"]["id"], amount=Decimal("500.00"), memo=None)
    repo.insert_schedule_line(conn, scheduled_entry_id=sched_id, line_no=2,
                               account_id=book["salary"]["id"], amount=Decimal("-500.00"), memo=None)
    lines = repo.schedule_lines(conn, sched_id)
    assert [ln["amount"] for ln in lines] == [Decimal("500.00"), Decimal("-500.00")]


def test_scheduled_all_orders_by_next_date_and_joins_scenario_and_payee(book, conn):
    later = _mk_bare_schedule(conn, book, next_date=date(2026, 10, 1))
    sooner = repo.insert_schedule(
        conn, description="Gym", reference=None, payee_id=book["payee"]["id"],
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=date(2026, 9, 1))
    repo.insert_schedule_line(conn, scheduled_entry_id=sooner, line_no=1,
                               account_id=book["checking"]["id"], amount=Decimal("50.00"), memo=None)
    repo.insert_schedule_line(conn, scheduled_entry_id=sooner, line_no=2,
                               account_id=book["salary"]["id"], amount=Decimal("-50.00"), memo=None)
    rows = repo.scheduled_all(conn)
    assert [r["id"] for r in rows] == [sooner, later]
    assert rows[0]["scenario_code"] == "ACTUAL"
    assert rows[0]["payee_name"] == "Employer Inc"
    assert rows[0]["line_count"] == 2
    assert rows[0]["total_amount"] == Decimal("50.00")
    assert rows[1]["line_count"] == 0  # bare schedule, no lines inserted


def test_toggle_schedule_active_flips_and_returns_row(book, conn):
    sched_id = _mk_bare_schedule(conn, book)
    row = repo.toggle_schedule_active(conn, sched_id)
    assert row == {"id": sched_id, "description": "Rent", "is_active": False}
    row = repo.toggle_schedule_active(conn, sched_id)
    assert row["is_active"] is True


def test_toggle_schedule_active_none_for_unknown_id(conn):
    assert repo.toggle_schedule_active(conn, 999999) is None


def test_due_schedules_excludes_future_dated_and_inactive(book, conn):
    today = date.today()
    due = _mk_bare_schedule(conn, book, next_date=today)
    future = _mk_bare_schedule(conn, book, next_date=today + timedelta(days=30))
    inactive = _mk_bare_schedule(conn, book, next_date=today)
    conn.execute(text("UPDATE scheduled_entries SET is_active = FALSE WHERE id = :id"),
                 {"id": inactive})
    ids = [r["id"] for r in repo.due_schedules(conn)]
    assert due in ids
    assert future not in ids
    assert inactive not in ids


def test_insert_staged_occurrence_sets_scheduled_entry_id(book, conn):
    sched_id = _mk_bare_schedule(conn, book)
    entry_id = repo.insert_staged_occurrence(
        conn, scenario_id=book["staging"]["id"], entry_date="2026-09-01", description="Rent",
        reference="REF-1", payee_id=book["payee"]["id"], scheduled_entry_id=sched_id)
    row = conn.execute(text(
        "SELECT scenario_id, scheduled_entry_id FROM journal_entries WHERE id = :id"
    ), {"id": entry_id}).mappings().one()
    assert row["scenario_id"] == book["staging"]["id"]
    assert row["scheduled_entry_id"] == sched_id


def test_insert_staged_line_and_check_deferred_constraints(book, conn):
    sched_id = _mk_bare_schedule(conn, book)
    entry_id = repo.insert_staged_occurrence(
        conn, scenario_id=book["staging"]["id"], entry_date="2026-09-01", description="Rent",
        reference=None, payee_id=None, scheduled_entry_id=sched_id)
    repo.insert_staged_line(conn, entry_id=entry_id, line_no=1, account_id=book["checking"]["id"],
                             amount=Decimal("100.00"), memo=None)
    repo.insert_staged_line(conn, entry_id=entry_id, line_no=2, account_id=book["salary"]["id"],
                             amount=Decimal("-50.00"), memo=None)
    with pytest.raises(DBAPIError, match="is not balanced"):
        repo.check_deferred_constraints(conn)


def test_check_deferred_constraints_raises_on_an_entry_with_no_lines(book, conn):
    sched_id = _mk_bare_schedule(conn, book)
    repo.insert_staged_occurrence(
        conn, scenario_id=book["staging"]["id"], entry_date="2026-09-01", description="Rent",
        reference=None, payee_id=None, scheduled_entry_id=sched_id)
    with pytest.raises(DBAPIError, match="has no lines"):
        repo.check_deferred_constraints(conn)


def test_advance_next_date_updates_the_one_row(book, conn):
    sched_id = _mk_bare_schedule(conn, book, next_date=date(2026, 9, 1))
    repo.advance_next_date(conn, sched_id, date(2026, 10, 1))
    row = conn.execute(
        text("SELECT next_date FROM scheduled_entries WHERE id = :id"), {"id": sched_id}
    ).mappings().one()
    assert row["next_date"] == date(2026, 10, 1)


def test_templates_all_and_lines_and_tags_for(book, conn):
    tpl_id = repo.insert_template(conn, name="Rent template", description="Rent",
                                   reference=None, payee_id=book["payee"]["id"])
    repo.insert_template_line(conn, template_id=tpl_id, line_no=1, account_id=book["checking"]["id"],
                               amount=Decimal("-500.00"), memo="out")
    repo.sync_tags(conn, "entry_template_tags", "template_id", tpl_id, ["rent"])
    templates = repo.templates_all(conn)
    assert [t["name"] for t in templates] == ["Rent template"]
    assert templates[0]["payee_name"] == "Employer Inc"
    lines = repo.template_lines_for(conn, [tpl_id])
    # Raw debit/credit straight off the generated columns here — both are
    # `NUMERIC NOT NULL` (never NULL), so the zero side reads back as
    # Decimal("0.00"), not None. `service.list_templates` is what turns a
    # zero side into `None` for the JSON response (str()-if-truthy) —
    # see test_service.py's own assertion on that shape.
    assert lines == [{"template_id": tpl_id, "code": "1100", "debit": Decimal("0.00"),
                       "credit": Decimal("500.00"), "memo": "out"}]
    tags = repo.template_tags_for(conn, [tpl_id])
    assert [t["name"] for t in tags] == ["rent"]


def test_delete_template_returns_rowcount(book, conn):
    tpl_id = repo.insert_template(conn, name="Once", description="x", reference=None, payee_id=None)
    assert repo.delete_template(conn, tpl_id) == 1
    assert repo.delete_template(conn, tpl_id) == 0
