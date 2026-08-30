"""DB-backed tests of modules.entries.service — the create/reverse/edit
business logic, including the two things that only actually happen at
this layer rather than in repository.py directly: `domain.entry.parse_
lines`/`parse_tags` validation running before any SQL, and (for
`reverse_entries_bulk`) the `SAVEPOINT`-per-entry isolation service.py's
own docstring explains."""
from datetime import date

import pytest
from sqlalchemy.exc import SQLAlchemyError

from postwarden.errors import pg_message
from postwarden.modules.entries import repository as repo
from postwarden.modules.entries import service


def _make(book, accounts=("1100", "4100"), debits=("500", ""), credits=("", "500"),
          memos=("", ""), **kw):
    defaults = dict(entry_date=date(2026, 3, 1), scenario_id=book["scenario"]["id"],
                     description="Paycheck", reference=None, tags="", payee_id=None,
                     accounts=list(accounts), debits=list(debits), credits=list(credits),
                     memos=list(memos))
    defaults.update(kw)
    return defaults


def test_create_entry_posts_a_balanced_entry_with_tags(book, conn):
    entry_id = service.create_entry(conn, **_make(book, tags="payroll, monthly"))
    lines = repo.lines_for_entries(conn, [entry_id])
    assert [l["account_code"] for l in lines] == ["1100", "4100"]
    assert {t["name"] for t in repo.tags_for_entries(conn, [entry_id])} == {"payroll", "monthly"}


def test_create_entry_defaults_entry_date_to_today(book, conn):
    entry_id = service.create_entry(conn, **{**_make(book), "entry_date": None})
    [entry] = service.list_entries(conn, entry_id=entry_id)["entries"]
    assert entry["entry_date"] == date.today()


def test_create_entry_rejects_an_unknown_account_code(book, conn):
    with pytest.raises(ValueError, match="Unknown account code: 9999"):
        service.create_entry(conn, **_make(book, accounts=["1100", "9999"]))


def test_create_entry_rejects_an_empty_description(book, conn):
    with pytest.raises(ValueError, match="Description is required"):
        service.create_entry(conn, **_make(book, description="   "))


def test_create_entry_surfaces_the_balance_trigger_as_a_dbapi_error(book, conn):
    # Individually valid lines (one debit, one credit, both positive) that
    # don't sum to zero across the entry — parse_lines has no opinion on
    # this, only the deferred trg_lines_balanced does.
    with pytest.raises(SQLAlchemyError) as exc_info:
        service.create_entry(conn, **_make(book, debits=("100", ""), credits=("", "50")))
    assert "is not balanced" in pg_message(exc_info.value)


def test_list_entries_filters_by_account_and_paginates(book, conn):
    ids = [service.create_entry(conn, **_make(book, description=f"Entry {i}")) for i in range(3)]
    result = service.list_entries(conn, account="1100", page_size=2)
    assert result["page_size"] == 2
    assert len(result["entries"]) == 2
    assert result["has_next"] is True
    assert result["has_prev"] is False
    all_ids = {e["id"] for e in result["entries"]}
    page2 = service.list_entries(conn, account="1100", page=2, page_size=2)
    all_ids |= {e["id"] for e in page2["entries"]}
    assert all_ids == set(ids)
    assert page2["has_next"] is False
    assert page2["has_prev"] is True


def test_list_entries_nests_lines_and_tags_under_each_entry(book, conn):
    entry_id = service.create_entry(conn, **_make(book, tags="payroll"))
    [entry] = service.list_entries(conn, entry_id=entry_id)["entries"]
    assert entry["tags"] == ["payroll"]
    assert {l["account_code"] for l in entry["lines"]} == {"1100", "4100"}


def test_reverse_entry_flips_amounts_and_carries_tags(book, conn):
    entry_id = service.create_entry(conn, **_make(book, tags="payroll"))
    new_id = service.reverse_entry(conn, entry_id)
    new_lines = {l["account_code"]: l for l in repo.lines_for_entries(conn, [new_id])}
    assert new_lines["1100"]["credit"] == 500
    assert new_lines["4100"]["debit"] == 500
    assert {t["name"] for t in repo.tags_for_entries(conn, [new_id])} == {"payroll"}
    assert repo.reversed_by(conn, entry_id) == new_id


def test_reverse_entry_rejects_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="not found"):
        service.reverse_entry(conn, "ZZZZZZ")


def test_reverse_entry_rejects_a_double_reversal(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    service.reverse_entry(conn, entry_id)
    with pytest.raises(ValueError, match="already reversed"):
        service.reverse_entry(conn, entry_id)


def test_reverse_entries_bulk_one_bad_id_does_not_stop_the_rest(book, conn):
    good = service.create_entry(conn, **_make(book))
    reversed_ids, errors = service.reverse_entries_bulk(conn, ["ZZZZZZ", good])
    assert reversed_ids != []
    assert errors == ["Entry #ZZZZZZ not found"]
    assert repo.reversed_by(conn, good) == reversed_ids[0]


def test_reverse_entries_bulk_a_duplicate_id_reverses_once_and_reports_the_second(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    reversed_ids, errors = service.reverse_entries_bulk(conn, [entry_id, entry_id])
    assert len(reversed_ids) == 1
    assert len(errors) == 1
    assert "already reversed" in errors[0]


def test_edit_entries_tags_add_then_remove(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    tag = service.edit_entries_tags(conn, [entry_id], "add", "urgent")
    assert tag == "urgent"
    assert {t["name"] for t in repo.tags_for_entries(conn, [entry_id])} == {"urgent"}
    service.edit_entries_tags(conn, [entry_id], "remove", "urgent")
    assert repo.tags_for_entries(conn, [entry_id]) == []


def test_edit_entries_tags_rejects_no_selection_or_bad_action(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    with pytest.raises(ValueError, match="No entries selected"):
        service.edit_entries_tags(conn, [], "add", "urgent")
    with pytest.raises(ValueError, match="Unknown action"):
        service.edit_entries_tags(conn, [entry_id], "frobnicate", "urgent")


def test_edit_description_updates_and_rejects_not_found(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    assert service.edit_description(conn, entry_id, "  New description  ") == "New description"
    with pytest.raises(ValueError, match="not found"):
        service.edit_description(conn, "ZZZZZZ", "x")
    with pytest.raises(ValueError, match="can't be empty"):
        service.edit_description(conn, entry_id, "   ")


def test_edit_line_memo_updates_clears_and_rejects_not_found(book, conn):
    entry_id = service.create_entry(conn, **_make(book))
    [line] = [l for l in repo.lines_for_entries(conn, [entry_id]) if l["account_code"] == "1100"]
    assert service.edit_line_memo(conn, line["id"], "  a note  ") == "a note"
    assert service.edit_line_memo(conn, line["id"], "   ") == ""
    with pytest.raises(ValueError, match="not found"):
        service.edit_line_memo(conn, 999999, "x")
