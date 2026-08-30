"""Direct tests of modules.entries.repository — proves the raw SQL
wiring (and, for `check_deferred_constraints`, the deferred-trigger
interaction that module's own docstring explains) against a real
Postgres. Not exhaustive: filter-combination and end-to-end assembly
behavior are covered by test_service.py/test_router.py instead — this
file just proves each function returns/does what its own docstring
says."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from postwarden.modules.entries import repository as repo


def test_account_ids_by_code_returns_only_what_exists(book, conn):
    found = repo.account_ids_by_code(conn, ["1100", "4100", "9999"])
    assert found == {"1100": book["checking"]["id"], "4100": book["salary"]["id"]}


def test_insert_entry_and_insert_line_round_trip(book, conn):
    entry_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-15",
                                  description="Test entry", reference="REF-1", payee_id=None)
    assert len(entry_id) == 6 and entry_id.isupper()
    repo.insert_line(conn, entry_id=entry_id, line_no=1, account_id=book["checking"]["id"],
                      amount=Decimal("100.00"), memo="in")
    repo.insert_line(conn, entry_id=entry_id, line_no=2, account_id=book["salary"]["id"],
                      amount=Decimal("-100.00"), memo=None)
    lines = repo.lines_for_entries(conn, [entry_id])
    assert [l["account_code"] for l in lines] == ["1100", "4100"]
    assert lines[0]["debit"] == Decimal("100.00")
    assert lines[1]["credit"] == Decimal("100.00")


def test_check_deferred_constraints_raises_on_an_unbalanced_entry(book, conn):
    entry_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-15",
                                  description="Unbalanced", reference=None, payee_id=None)
    repo.insert_line(conn, entry_id=entry_id, line_no=1, account_id=book["checking"]["id"],
                      amount=Decimal("100.00"), memo=None)
    repo.insert_line(conn, entry_id=entry_id, line_no=2, account_id=book["salary"]["id"],
                      amount=Decimal("-50.00"), memo=None)
    with pytest.raises(DBAPIError, match="is not balanced"):
        repo.check_deferred_constraints(conn)


def test_check_deferred_constraints_raises_on_an_entry_with_no_lines(book, conn):
    entry_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-15",
                                  description="No lines", reference=None, payee_id=None)
    with pytest.raises(DBAPIError, match="has no lines"):
        repo.check_deferred_constraints(conn)


def test_sync_entry_tags_replaces_and_reactivates(book, conn):
    entry_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-15",
                                  description="Tagged", reference=None, payee_id=None)
    repo.sync_entry_tags(conn, entry_id, ["payroll", "monthly"])
    assert {t["name"] for t in repo.tags_for_entries(conn, [entry_id])} == {"payroll", "monthly"}
    # Full replace, not additive: "monthly" drops off, "urgent" is new.
    repo.sync_entry_tags(conn, entry_id, ["payroll", "urgent"])
    assert {t["name"] for t in repo.tags_for_entries(conn, [entry_id])} == {"payroll", "urgent"}
    # An archived tag comes back active once re-attached.
    conn.execute(text("UPDATE tags SET is_active = FALSE WHERE name = 'urgent'"))
    repo.sync_entry_tags(conn, entry_id, ["urgent"])
    row = conn.execute(text("SELECT is_active FROM tags WHERE name = 'urgent'")).mappings().one()
    assert row["is_active"] is True


def test_add_and_remove_tag_from_entries_is_additive_not_a_full_replace(book, conn, posted_entry):
    other_entry = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-16",
                                     description="Other", reference=None, payee_id=None)
    repo.insert_line(conn, entry_id=other_entry, line_no=1, account_id=book["checking"]["id"],
                      amount=Decimal("10.00"), memo=None)
    repo.insert_line(conn, entry_id=other_entry, line_no=2, account_id=book["salary"]["id"],
                      amount=Decimal("-10.00"), memo=None)
    repo.sync_entry_tags(conn, posted_entry, ["existing"])

    repo.add_tag_to_entries(conn, [posted_entry, other_entry], "shared")
    posted_tags = {t["name"] for t in repo.tags_for_entries(conn, [posted_entry])}
    other_tags = {t["name"] for t in repo.tags_for_entries(conn, [other_entry])}
    assert posted_tags == {"existing", "shared"}
    assert other_tags == {"shared"}

    repo.remove_tag_from_entries(conn, [posted_entry, other_entry], "shared")
    assert {t["name"] for t in repo.tags_for_entries(conn, [posted_entry])} == {"existing"}
    assert repo.tags_for_entries(conn, [other_entry]) == []


def test_entry_for_reverse_and_reversed_by(book, conn, posted_entry):
    orig = repo.entry_for_reverse(conn, posted_entry)
    assert orig["scenario_id"] == book["scenario"]["id"]
    assert orig["description"] == "Paycheck"
    assert repo.reversed_by(conn, posted_entry) is None

    new_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-17",
                                description=f"Reversal of #{posted_entry}", reference=None,
                                payee_id=None, reverses_entry_id=posted_entry)
    assert repo.reversed_by(conn, posted_entry) == new_id


def test_copy_lines_reversed_flips_amounts(book, conn, posted_entry):
    new_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-17",
                                description="Reversal", reference=None, payee_id=None,
                                reverses_entry_id=posted_entry)
    repo.copy_lines_reversed(conn, new_id, posted_entry)
    orig_lines = {l["account_code"]: l for l in repo.lines_for_entries(conn, [posted_entry])}
    new_lines = {l["account_code"]: l for l in repo.lines_for_entries(conn, [new_id])}
    assert new_lines["1100"]["credit"] == orig_lines["1100"]["debit"]
    assert new_lines["4100"]["debit"] == orig_lines["4100"]["credit"]


def test_copy_tags_carries_the_originals_tags(book, conn, posted_entry):
    repo.sync_entry_tags(conn, posted_entry, ["payroll"])
    new_id = repo.insert_entry(conn, scenario_id=book["scenario"]["id"], entry_date="2026-03-17",
                                description="Reversal", reference=None, payee_id=None,
                                reverses_entry_id=posted_entry)
    repo.copy_tags(conn, new_id, posted_entry)
    assert {t["name"] for t in repo.tags_for_entries(conn, [new_id])} == {"payroll"}


def test_update_description_rowcount_distinguishes_not_found(book, conn, posted_entry):
    assert repo.update_description(conn, posted_entry, "Updated") == 1
    assert repo.update_description(conn, "ZZZZZZ", "Updated") == 0


def test_update_line_memo_rowcount_distinguishes_not_found(book, conn, posted_entry):
    [line] = [l for l in repo.lines_for_entries(conn, [posted_entry]) if l["account_code"] == "1100"]
    assert repo.update_line_memo(conn, line["id"], "note") == 1
    assert repo.update_line_memo(conn, 999999, "note") == 0


def test_build_filter_defaults_to_excluding_staging_with_no_other_clause():
    where, params = repo.build_filter()
    assert where == ["NOT s.is_staging"]
    assert params == {}


def test_build_filter_between_sorts_the_bounds_regardless_of_argument_order():
    where, params = repo.build_filter(amount_op="between", amount_value="500", amount_value2="100")
    assert params["amount_lo"] == Decimal("100.00")
    assert params["amount_hi"] == Decimal("500.00")


def test_build_filter_ignores_a_garbage_amount_value():
    where, params = repo.build_filter(amount_op="gte", amount_value="not-a-number")
    assert "amount_value" not in params
    assert len(where) == 1  # just the unconditional NOT s.is_staging


def test_build_filter_and_list_entries_end_to_end(book, conn, posted_entry):
    where, params = repo.build_filter(account="1100")
    rows = repo.list_entries(conn, where, params, limit=10, offset=0)
    assert [r["id"] for r in rows] == [posted_entry]
    assert rows[0]["total_debits"] == Decimal("500.00")
    assert rows[0]["total_credits"] == Decimal("500.00")
    assert rows[0]["reversed_by"] is None
