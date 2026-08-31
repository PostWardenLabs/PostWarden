"""DB-backed tests of modules.staging.service — approve/reject/edit/
merge business logic, including `_validate_pending`'s consolidated
eligibility check and the `SAVEPOINT`-per-entry isolation `approve_
entries`/`reject_entries` both rely on (see service.py's own
docstring)."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from postwarden.errors import pg_message
from postwarden.modules.staging import repository as repo
from postwarden.modules.staging import service

from ...conftest import mk_entry, mk_line
from .conftest import mk_schedule


def _second_staged_entry(conn, book, description="Second", entry_date="2026-03-01",
                          checking_amount=500, salary_amount=-500):
    sched_id = mk_schedule(conn, book["actual"]["id"])
    entry_id = mk_entry(conn, book["staging"]["id"], entry_date, description,
                         scheduled_entry_id=sched_id)
    mk_line(conn, entry_id, book["checking"]["id"], checking_amount, 1)
    mk_line(conn, entry_id, book["salary"]["id"], salary_amount, 2)
    return entry_id


def test_validate_pending_rejects_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="not a pending staging entry"):
        service._validate_pending(conn, "ZZZZZZ")


def test_validate_pending_rejects_a_non_staging_entry(book, conn):
    entry_id = mk_entry(conn, book["actual"]["id"], "2026-03-01", "Posted directly")
    with pytest.raises(ValueError, match="not a pending staging entry"):
        service._validate_pending(conn, entry_id)


def test_validate_pending_rejects_an_already_approved_entry(book, conn, staged_entry):
    posted_id = mk_entry(conn, book["actual"]["id"], "2026-03-01", "Posted")
    repo.mark_promoted(conn, staged_entry, posted_id)
    with pytest.raises(ValueError, match="already approved"):
        service._validate_pending(conn, staged_entry)


def test_list_pending_nests_lines_and_tags_under_the_entry(book, conn, staged_entry):
    repo.sync_entry_tags(conn, staged_entry, ["payroll"])
    [entry] = service.list_pending(conn)["entries"]
    assert entry["id"] == staged_entry
    assert entry["tags"] == ["payroll"]
    assert {l["account_code"] for l in entry["lines"]} == {"1100", "4100"}


def test_list_pending_filters_by_target_scenario(book, conn, staged_entry):
    assert len(service.list_pending(conn, target_scenario="ACTUAL")["entries"]) == 1
    assert service.list_pending(conn, target_scenario="NOPE")["entries"] == []


def test_approve_entry_posts_into_target_scenario_and_marks_promoted(book, conn, staged_entry):
    new_id = service.approve_entry(conn, staged_entry)
    new_lines = {l["account_code"]: l for l in repo.lines_for_entries(conn, [new_id])}
    assert new_lines["1100"]["debit"] == Decimal("500.00")
    staged = repo.staged_entry(conn, staged_entry)
    assert staged["promoted_entry_id"] == new_id


def test_approve_entry_rejects_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="not a pending staging entry"):
        service.approve_entry(conn, "ZZZZZZ")


def test_approve_entry_surfaces_a_locked_target_scenario_as_a_dbapi_error(book, conn, staged_entry):
    conn.execute(text("UPDATE scenarios SET is_locked = TRUE WHERE id = :id"),
                 {"id": book["actual"]["id"]})
    with pytest.raises(SQLAlchemyError) as exc_info:
        service.approve_entry(conn, staged_entry)
    assert "locked" in pg_message(exc_info.value).lower()


def test_approve_entries_bulk_one_bad_id_does_not_stop_the_rest(book, conn, staged_entry):
    approved, errors = service.approve_entries(conn, ["ZZZZZZ", staged_entry])
    assert approved != []
    assert errors == ["#ZZZZZZ: not a pending staging entry"]
    assert repo.staged_entry(conn, staged_entry)["promoted_entry_id"] == approved[0]


def test_get_edit_data_returns_entry_lines_tags_and_target_scenario_id(book, conn, staged_entry):
    repo.sync_entry_tags(conn, staged_entry, ["payroll"])
    data = service.get_edit_data(conn, staged_entry)
    assert data["entry"]["id"] == staged_entry
    assert data["entry"]["description"] == "Paycheck"
    assert data["target_scenario_id"] == book["actual"]["id"]
    assert data["tags"] == ["payroll"]
    assert {l["account_code"] for l in data["lines"]} == {"1100", "4100"}


def test_get_edit_data_rejects_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="not a pending staging entry"):
        service.get_edit_data(conn, "ZZZZZZ")


def test_save_edit_replaces_lines_and_updates_the_header(book, conn, staged_entry):
    service.save_edit(conn, staged_entry, entry_date=None, description="  Rent  ",
                       reference=None, payee_id=None, tags="rent",
                       accounts=["1100", "4100"], debits=["200", ""], credits=["", "200"],
                       memos=["", ""])
    data = service.get_edit_data(conn, staged_entry)
    assert data["entry"]["description"] == "Rent"
    assert data["tags"] == ["rent"]
    lines = {l["account_code"]: l for l in data["lines"]}
    assert lines["1100"]["debit"] == Decimal("200.00")


def test_save_edit_rejects_an_unknown_account_code(book, conn, staged_entry):
    with pytest.raises(ValueError, match="Unknown account code: 9999"):
        service.save_edit(conn, staged_entry, entry_date=None, description="x", reference=None,
                           payee_id=None, tags="", accounts=["9999", "4100"],
                           debits=["10", ""], credits=["", "10"], memos=["", ""])


def test_save_edit_rejects_an_empty_description(book, conn, staged_entry):
    with pytest.raises(ValueError, match="Description is required"):
        service.save_edit(conn, staged_entry, entry_date=None, description="   ", reference=None,
                           payee_id=None, tags="", accounts=["1100", "4100"],
                           debits=["10", ""], credits=["", "10"], memos=["", ""])


def test_reject_entry_deletes_lines_and_the_entry(book, conn, staged_entry):
    service.reject_entry(conn, staged_entry)
    assert repo.staged_entry(conn, staged_entry) is None


def test_reject_entry_rejects_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="not a pending staging entry"):
        service.reject_entry(conn, "ZZZZZZ")


def test_reject_entries_bulk_one_bad_id_does_not_stop_the_rest(book, conn, staged_entry):
    rejected, errors = service.reject_entries(conn, ["ZZZZZZ", staged_entry])
    assert rejected == [staged_entry]
    assert errors == ["#ZZZZZZ: not a pending staging entry"]
    assert repo.staged_entry(conn, staged_entry) is None


def test_find_duplicate_groups_groups_entries_with_matching_date_and_legs(book, conn, staged_entry):
    dup_id = _second_staged_entry(conn, book)
    [group] = service.find_duplicate_groups(conn)
    assert {e["id"] for e in group["entries"]} == {staged_entry, dup_id}
    assert "Salary" in group["label"] and "Checking" in group["label"]


def test_find_duplicate_groups_ignores_entries_that_dont_match(book, conn, staged_entry):
    _second_staged_entry(conn, book, description="Different amount", checking_amount=999,
                          salary_amount=-999)
    assert service.find_duplicate_groups(conn) == []


def test_find_duplicate_groups_ignores_entries_on_a_different_date(book, conn, staged_entry):
    _second_staged_entry(conn, book, entry_date="2026-04-01")
    assert service.find_duplicate_groups(conn) == []


def test_merge_duplicates_keeps_the_survivor_and_deletes_the_rest(book, conn, staged_entry):
    dup_id = _second_staged_entry(conn, book)
    [checking_line] = [l for l in repo.lines_for_entries(conn, [staged_entry])
                        if l["account_code"] == "1100"]
    service.merge_duplicates(
        conn, keep_id=staged_entry, remove_ids=[dup_id], description="Merged paycheck",
        reference="REF-1", payee_id=None, tags="payroll",
        line_memos={str(checking_line["id"]): "kept memo"})
    assert repo.staged_entry(conn, dup_id) is None
    data = service.get_edit_data(conn, staged_entry)
    assert data["entry"]["description"] == "Merged paycheck"
    assert data["tags"] == ["payroll"]
    kept_line = [l for l in data["lines"] if l["id"] == checking_line["id"]][0]
    assert kept_line["memo"] == "kept memo"


def test_merge_duplicates_rejects_an_empty_selection(book, conn, staged_entry):
    with pytest.raises(ValueError, match="Select at least two entries"):
        service.merge_duplicates(conn, keep_id=staged_entry, remove_ids=[], description="x",
                                  reference=None, payee_id=None, tags="", line_memos={})


def test_merge_duplicates_rejects_an_empty_description(book, conn, staged_entry):
    dup_id = _second_staged_entry(conn, book)
    with pytest.raises(ValueError, match="Description can't be empty"):
        service.merge_duplicates(conn, keep_id=staged_entry, remove_ids=[dup_id], description="   ",
                                  reference=None, payee_id=None, tags="", line_memos={})
