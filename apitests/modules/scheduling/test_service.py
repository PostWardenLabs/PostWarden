"""DB-backed tests of modules.scheduling.service — schedule/template
creation validation, and `materialize_due_schedules`'s own due-date
filtering, per-schedule `SAVEPOINT` isolation, and `next_date`
advancement (service.py's own docstring explains why the SAVEPOINT is
there at all, the same reasoning `modules/entries/service.py`'s own
`reverse_entries_bulk` test file already covers for the Journal)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from ...conftest import mk_account, mk_scenario
from postwarden.modules.scheduling import repository as repo
from postwarden.modules.scheduling import service


def _schedule(book, accounts=("1100", "4100"), debits=("500", ""), credits=("", "500"), **kw):
    defaults = dict(description="Rent", reference=None, payee_id=None,
                     target_scenario_id=book["actual"]["id"], interval_unit="month",
                     interval_count=1, next_date=date.today(), tags="",
                     accounts=list(accounts), debits=list(debits), credits=list(credits),
                     memos=["", ""])
    defaults.update(kw)
    return defaults


def _template(book, accounts=("1100", "4100"), debits=("500", ""), credits=("", "500"), **kw):
    defaults = dict(name="Rent template", description="Rent", reference=None, payee_id=None,
                     tags="", accounts=list(accounts), debits=list(debits), credits=list(credits),
                     memos=["", ""])
    defaults.update(kw)
    return defaults


# ---------------------------------------------------------------------------
# Scheduled entries
# ---------------------------------------------------------------------------

def test_create_schedule_happy_path_with_tags(book, conn):
    sched_id = service.create_schedule(conn, **_schedule(book, tags="rent, monthly"))
    [row] = [r for r in repo.scheduled_all(conn) if r["id"] == sched_id]
    assert row["description"] == "Rent"
    assert set(repo.schedule_tag_names(conn, sched_id)) == {"rent", "monthly"}


def test_create_schedule_rejects_unbalanced_lines(book, conn):
    with pytest.raises(ValueError, match="must balance"):
        service.create_schedule(conn, **_schedule(book, debits=("500", ""), credits=("", "400")))


def test_create_schedule_rejects_missing_description(book, conn):
    with pytest.raises(ValueError, match="Description is required"):
        service.create_schedule(conn, **_schedule(book, description="  "))


def test_create_schedule_rejects_non_positive_interval_count(book, conn):
    with pytest.raises(ValueError, match="Repeat count must be positive"):
        service.create_schedule(conn, **_schedule(book, interval_count=0))


def test_create_schedule_rejects_an_unknown_account_code(book, conn):
    with pytest.raises(ValueError, match="Unknown account code: 9999"):
        service.create_schedule(conn, **_schedule(book, accounts=("9999", "4100")))


def test_create_schedule_defaults_next_date_to_today(book, conn):
    sched_id = service.create_schedule(conn, **{**_schedule(book), "next_date": None})
    row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                        {"id": sched_id}).mappings().one()
    assert row["next_date"] == date.today()


def test_toggle_schedule_active_flips_and_raises_on_unknown_id(book, conn):
    sched_id = service.create_schedule(conn, **_schedule(book))
    row = service.toggle_schedule_active(conn, sched_id)
    assert row["is_active"] is False
    with pytest.raises(ValueError, match="not found"):
        service.toggle_schedule_active(conn, 999999)


# ---------------------------------------------------------------------------
# materialize_due_schedules
# ---------------------------------------------------------------------------

def test_materialize_due_schedules_posts_a_staged_occurrence_and_advances_next_date(book, conn):
    sched_id = service.create_schedule(conn, **_schedule(
        book, next_date=date(2026, 8, 29), interval_unit="month", interval_count=1, tags="rent"))
    materialized, errors = service.materialize_due_schedules(conn)
    assert materialized == [sched_id]
    assert errors == []

    entry = conn.execute(text("""
        SELECT id, scenario_id, scheduled_entry_id, description FROM journal_entries
         WHERE scheduled_entry_id = :id
    """), {"id": sched_id}).mappings().one()
    assert entry["scenario_id"] == book["staging"]["id"]
    assert entry["description"] == "Rent"
    lines = conn.execute(text(
        "SELECT account_id, amount FROM journal_lines WHERE entry_id = :id ORDER BY line_no"
    ), {"id": entry["id"]}).mappings().all()
    assert [(l["account_id"], l["amount"]) for l in lines] == [
        (book["checking"]["id"], Decimal("500.00")), (book["salary"]["id"], Decimal("-500.00"))]
    tag = conn.execute(text("""
        SELECT tg.name FROM journal_entry_tags jet JOIN tags tg ON tg.id = jet.tag_id
         WHERE jet.entry_id = :id
    """), {"id": entry["id"]}).mappings().one()
    assert tag["name"] == "rent"

    row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                        {"id": sched_id}).mappings().one()
    assert row["next_date"] == date(2026, 9, 29)


def test_materialize_due_schedules_ignores_schedules_not_yet_due(book, conn):
    future = date.today() + timedelta(days=30)
    sched_id = service.create_schedule(conn, **_schedule(book, next_date=future))
    assert service.materialize_due_schedules(conn) == ([], [])
    row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                        {"id": sched_id}).mappings().one()
    assert row["next_date"] == future


def test_materialize_due_schedules_skips_inactive_schedules(book, conn):
    sched_id = service.create_schedule(conn, **_schedule(book, next_date=date.today()))
    service.toggle_schedule_active(conn, sched_id)  # now inactive
    assert service.materialize_due_schedules(conn) == ([], [])


def test_materialize_due_schedules_skips_a_schedule_with_no_lines(book, conn):
    sched_id = repo.insert_schedule(
        conn, description="Empty", reference=None, payee_id=None,
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=date.today())
    materialized, errors = service.materialize_due_schedules(conn)
    assert materialized == []
    assert errors == []
    row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                        {"id": sched_id}).mappings().one()
    assert row["next_date"] == date.today()  # left alone, not advanced


def test_materialize_due_schedules_no_staging_scenario_configured(conn):
    actual = mk_scenario(conn, "ACTUAL")
    checking = mk_account(conn, "1100", "Checking", "asset")
    sched_id = repo.insert_schedule(
        conn, description="Rent", reference=None, payee_id=None,
        target_scenario_id=actual["id"], interval_unit="month",
        interval_count=1, next_date=date.today())
    repo.insert_schedule_line(conn, scheduled_entry_id=sched_id, line_no=1,
                               account_id=checking["id"], amount=Decimal("1.00"), memo=None)
    assert service.materialize_due_schedules(conn) == ([], [])


def test_materialize_due_schedules_one_bad_schedule_does_not_stop_the_rest(book, conn):
    good = service.create_schedule(conn, **_schedule(book, next_date=date.today()))
    bad = repo.insert_schedule(
        conn, description="Bad", reference=None, payee_id=None,
        target_scenario_id=book["actual"]["id"], interval_unit="month",
        interval_count=1, next_date=date.today())
    repo.insert_schedule_line(conn, scheduled_entry_id=bad, line_no=1,
                               account_id=book["checking"]["id"], amount=Decimal("100.00"), memo=None)

    materialized, errors = service.materialize_due_schedules(conn)
    assert materialized == [good]
    assert len(errors) == 1 and "not balanced" in errors[0]
    good_row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                             {"id": good}).mappings().one()
    assert good_row["next_date"] > date.today()
    bad_row = conn.execute(text("SELECT next_date FROM scheduled_entries WHERE id = :id"),
                            {"id": bad}).mappings().one()
    assert bad_row["next_date"] == date.today()  # rolled back to its own savepoint, unchanged


# ---------------------------------------------------------------------------
# Entry templates
# ---------------------------------------------------------------------------

def test_create_template_and_list_templates_nests_lines_and_tags(book, conn):
    tpl_id = service.create_template(conn, **_template(book, tags="rent"))
    [tpl] = service.list_templates(conn)
    assert tpl["id"] == tpl_id
    assert tpl["lines"] == [
        {"code": "1100", "debit": "500.00", "credit": None, "memo": None},
        {"code": "4100", "debit": None, "credit": "500.00", "memo": None},
    ]
    assert tpl["tags"] == ["rent"]


def test_create_template_rejects_missing_name(book, conn):
    with pytest.raises(ValueError, match="name is required"):
        service.create_template(conn, **_template(book, name="  "))


def test_create_template_rejects_unbalanced_lines(book, conn):
    with pytest.raises(ValueError, match="must balance"):
        service.create_template(conn, **_template(book, debits=("500", ""), credits=("", "400")))


def test_create_template_rejects_missing_description(book, conn):
    with pytest.raises(ValueError, match="Description is required"):
        service.create_template(conn, **_template(book, description=" "))


def test_create_template_rejects_an_unknown_account_code(book, conn):
    with pytest.raises(ValueError, match="Unknown account code: 9999"):
        service.create_template(conn, **_template(book, accounts=("9999", "4100")))


def test_delete_template_raises_on_unknown_id(book, conn):
    tpl_id = service.create_template(conn, **_template(book))
    service.delete_template(conn, tpl_id)
    with pytest.raises(ValueError, match="not found"):
        service.delete_template(conn, tpl_id)
