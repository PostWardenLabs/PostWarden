"""Direct tests of modules.staging.repository — proves the raw SQL
wiring against a real Postgres. Filter-combination and end-to-end
assembly behavior are covered by test_service.py/test_router.py
instead — this file just proves each function returns/does what its
own docstring says."""
from decimal import Decimal

from sqlalchemy import text

from postwarden.modules.staging import repository as repo

from ...conftest import mk_entry, mk_line
from .conftest import mk_schedule


def test_actual_scenario_id_returns_none_when_no_actual_scenario_exists(conn):
    assert repo.actual_scenario_id(conn) is None


def test_actual_scenario_id_returns_the_actual_scenario(book, conn):
    assert repo.actual_scenario_id(conn) == book["actual"]["id"]


def test_account_ids_by_code_returns_only_what_exists(book, conn):
    found = repo.account_ids_by_code(conn, ["1100", "4100", "9999"])
    assert found == {"1100": book["checking"]["id"], "4100": book["salary"]["id"]}


def test_staged_entry_returns_none_for_an_unknown_id(conn):
    assert repo.staged_entry(conn, "ZZZZZZ") is None


def test_staged_entry_resolves_target_scenario_from_its_schedule(book, conn, staged_entry):
    staged = repo.staged_entry(conn, staged_entry)
    assert staged["is_staging"] is True
    assert staged["promoted_entry_id"] is None
    assert staged["target_scenario_id"] == book["actual"]["id"]


def test_insert_entry_copy_lines_copy_tags_and_mark_promoted_round_trip(book, conn, staged_entry):
    repo.sync_entry_tags(conn, staged_entry, ["payroll"])
    new_id = repo.insert_entry(conn, scenario_id=book["actual"]["id"], entry_date="2026-03-01",
                                description="Paycheck", reference=None, payee_id=None)
    repo.copy_lines(conn, new_id, staged_entry)
    repo.copy_tags(conn, new_id, staged_entry)
    repo.mark_promoted(conn, staged_entry, new_id)

    new_lines = {l["account_code"]: l for l in repo.lines_for_entries(conn, [new_id])}
    assert new_lines["1100"]["debit"] == Decimal("500.00")  # not sign-flipped, unlike a reversal
    assert new_lines["4100"]["credit"] == Decimal("500.00")
    assert {t["name"] for t in repo.tags_for_entries(conn, [new_id])} == {"payroll"}

    staged = repo.staged_entry(conn, staged_entry)
    assert staged["promoted_entry_id"] == new_id


def test_build_filter_defaults_to_excluding_already_promoted_entries():
    where, params = repo.build_filter()
    assert where == ["e.promoted_entry_id IS NULL"]
    assert params == {}


def test_build_filter_target_scenario_adds_the_coalesced_clause():
    where, params = repo.build_filter(target_scenario="ACTUAL")
    assert "COALESCE(ts.code, ib_ts.code) = :target_scenario" in where
    assert params["target_scenario"] == "ACTUAL"


def test_list_pending_entries_end_to_end(book, conn, staged_entry):
    where, params = repo.build_filter()
    [row] = repo.list_pending_entries(conn, where, params)
    assert row["id"] == staged_entry
    assert row["target_scenario_code"] == "ACTUAL"
    assert row["schedule_description"] == "Rent"
    assert row["import_filename"] is None
    assert row["total_debits"] == Decimal("500.00")


def test_update_entry_header_updates_every_field(book, conn, staged_entry):
    repo.update_entry_header(conn, staged_entry, entry_date="2026-04-15", description="Updated",
                              reference="REF-9", payee_id=None)
    [row] = repo.list_pending_entries(conn, *repo.build_filter())
    assert row["entry_date"].isoformat() == "2026-04-15"
    assert row["description"] == "Updated"
    assert row["reference"] == "REF-9"


def test_replace_lines_deletes_then_reinserts(book, conn, staged_entry):
    repo.replace_lines(conn, staged_entry, [
        {"account_id": book["checking"]["id"], "amount": Decimal("100.00"), "memo": "new"},
    ])
    [line] = repo.lines_for_entries(conn, [staged_entry])
    assert line["account_code"] == "1100"
    assert line["debit"] == Decimal("100.00")
    assert line["memo"] == "new"


def test_line_ids_for_entry_and_update_line_memo(book, conn, staged_entry):
    [checking_line] = [l for l in repo.lines_for_entries(conn, [staged_entry])
                        if l["account_code"] == "1100"]
    assert checking_line["id"] in repo.line_ids_for_entry(conn, staged_entry)
    repo.update_line_memo(conn, checking_line["id"], "a note")
    [updated] = [l for l in repo.lines_for_entries(conn, [staged_entry])
                 if l["id"] == checking_line["id"]]
    assert updated["memo"] == "a note"


def test_delete_lines_for_entry_and_delete_entry(book, conn, staged_entry):
    repo.delete_lines_for_entry(conn, staged_entry)
    assert repo.lines_for_entries(conn, [staged_entry]) == []
    repo.delete_entry(conn, staged_entry)
    assert repo.staged_entry(conn, staged_entry) is None


def test_all_pending_entries_basic_includes_already_promoted_entries(book, conn, staged_entry):
    # Ported quirk, not a bug fix — see this function's own docstring:
    # legacy's duplicate-finder never filtered on promoted_entry_id, so
    # an already-approved staging-origin entry stays a candidate.
    posted_id = mk_entry(conn, book["actual"]["id"], "2026-03-01", "Posted")
    repo.mark_promoted(conn, staged_entry, posted_id)
    ids = {e["id"] for e in repo.all_pending_entries_basic(conn)}
    assert staged_entry in ids


def test_lines_for_entries_signed_returns_the_signed_amount(book, conn, staged_entry):
    lines = {l["account_code"]: l for l in repo.lines_for_entries_signed(conn, [staged_entry])}
    assert lines["1100"]["amount"] == Decimal("500.00")
    assert lines["4100"]["amount"] == Decimal("-500.00")


def test_delete_entries_and_delete_lines_for_entries_are_bulk(book, conn):
    sched_id = mk_schedule(conn, book["actual"]["id"])
    e1 = mk_entry(conn, book["staging"]["id"], "2026-03-01", "A", scheduled_entry_id=sched_id)
    e2 = mk_entry(conn, book["staging"]["id"], "2026-03-02", "B", scheduled_entry_id=sched_id)
    mk_line(conn, e1, book["checking"]["id"], 10, 1)
    mk_line(conn, e2, book["checking"]["id"], 20, 1)
    repo.delete_lines_for_entries(conn, [e1, e2])
    assert repo.lines_for_entries(conn, [e1, e2]) == []
    repo.delete_entries(conn, [e1, e2])
    assert repo.staged_entry(conn, e1) is None
    assert repo.staged_entry(conn, e2) is None
