"""Direct tests of modules.reference.repository — one assertion per
query/mutation, against the `book` fixture in `conftest.py`."""
from sqlalchemy import text

from postwarden.modules.reference import repository as repo


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def test_list_accounts_returns_the_whole_chart_by_default(book, conn):
    codes = {a["code"] for a in repo.list_accounts(conn)}
    assert codes == {"1000", "1100", "4000", "4100"}


def test_list_accounts_filters_by_level_depth(book, conn):
    # Checking/Salary (leaves, depth 2) sit one level below Assets/Income
    # (depth 1) — book["level"] is depth 1.
    rows = repo.list_accounts(conn, level_id=book["level"]["id"])
    assert {r["code"] for r in rows} == {"1000", "4000"}


def test_list_accounts_returns_empty_for_an_unknown_level(book, conn):
    assert repo.list_accounts(conn, level_id=999999) == []


def test_next_account_code_increments_within_the_type_prefix(book, conn):
    # 1000/1100 already exist; next asset code should be higher than both.
    code = repo.next_account_code(conn, "asset")
    assert code.startswith("1")
    assert int(code) > 1100


def test_next_account_code_starts_fresh_for_an_unused_prefix(book, conn):
    assert repo.next_account_code(conn, "equity") == "3000"


def test_account_type_of_returns_none_for_an_unknown_id(book, conn):
    assert repo.account_type_of(conn, 999999) is None
    assert repo.account_type_of(conn, book["checking"]["id"]) == "asset"


def test_insert_account_creates_a_leaf(book, conn):
    row = repo.insert_account(conn, code="1200", name="Savings", account_type="asset",
                               parent_id=book["assets"]["id"], is_postable=True, is_cashflow=True)
    assert row["code"] == "1200"
    assert {a["code"] for a in repo.list_accounts(conn)} >= {"1200"}


def test_toggle_account_active_flips_and_returns_new_state(book, conn):
    row = repo.toggle_account_active(conn, book["checking"]["id"])
    assert row["is_active"] is False
    row2 = repo.toggle_account_active(conn, book["checking"]["id"])
    assert row2["is_active"] is True


def test_toggle_account_active_returns_none_for_an_unknown_id(book, conn):
    assert repo.toggle_account_active(conn, 999999) is None


def test_toggle_account_cashflow_flips_and_returns_new_state(book, conn):
    row = repo.toggle_account_cashflow(conn, book["checking"]["id"])
    assert row["is_cashflow"] is False


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

def test_account_levels_all_includes_scenario_count(book, conn):
    rows = repo.account_levels_all(conn)
    row = next(r for r in rows if r["id"] == book["level"]["id"])
    assert row["scenario_count"] == 0  # no scenario points its base_level_id here


def test_insert_account_level(book, conn):
    row = repo.insert_account_level(conn, "Subaccounts", 2)
    assert row["depth"] == 2


def test_rename_account_level_rowcount(book, conn):
    assert repo.rename_account_level(conn, book["level"]["id"], "Renamed") == 1
    assert repo.rename_account_level(conn, 999999, "Nope") == 0


def test_delete_account_level_rowcount(book, conn):
    assert repo.delete_account_level(conn, book["level"]["id"]) == 1
    assert repo.delete_account_level(conn, 999999) == 0


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_scenarios_all_includes_entry_count(book, conn):
    rows = repo.scenarios_all(conn)
    row = next(r for r in rows if r["id"] == book["actual"]["id"])
    assert row["entry_count"] == 2


def test_insert_scenario(book, conn):
    row = repo.insert_scenario(conn, code="BUD", name="Budget", scenario_type="budget",
                                enforce_balance=False, income_statement_only=True,
                                base_level_id=None, notes=None)
    assert row["code"] == "BUD"


def test_toggle_scenario_lock_flips_and_returns_new_state(book, conn):
    row = repo.toggle_scenario_lock(conn, book["actual"]["id"])
    assert row["is_locked"] is True


def test_toggle_scenario_lock_returns_none_for_an_unknown_id(book, conn):
    assert repo.toggle_scenario_lock(conn, 999999) is None


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

def test_payees_all_includes_entry_count(book, conn):
    rows = repo.payees_all(conn)
    acme = next(r for r in rows if r["id"] == book["acme"]["id"])
    other = next(r for r in rows if r["id"] == book["other"]["id"])
    assert acme["entry_count"] == 1
    assert other["entry_count"] == 1


def test_insert_payee(book, conn):
    row = repo.insert_payee(conn, "New Payee")
    assert row["name"] == "New Payee"


def test_quick_create_payee_reactivates_an_archived_one(book, conn):
    repo.toggle_payee_active(conn, book["acme"]["id"])  # archive it
    row = repo.quick_create_payee(conn, "Acme")
    assert row["id"] == book["acme"]["id"]
    active = next(r for r in repo.payees_all(conn) if r["id"] == book["acme"]["id"])
    assert active["is_active"] is True


def test_toggle_payee_active_returns_none_for_an_unknown_id(book, conn):
    assert repo.toggle_payee_active(conn, 999999) is None


def test_rename_payee_rowcount(book, conn):
    assert repo.rename_payee(conn, book["acme"]["id"], "Acme Corp") == 1
    assert repo.rename_payee(conn, 999999, "Nope") == 0


def test_delete_payee_returns_name_or_none(book, conn):
    assert repo.delete_payee(conn, book["other"]["id"]) == "Other Co"
    assert repo.delete_payee(conn, 999999) is None


def test_delete_payee_nulls_out_the_entry_it_was_on(book, conn):
    repo.delete_payee(conn, book["acme"]["id"])
    row = conn.execute(
        text("SELECT payee_id FROM journal_entries WHERE id = :id"),
        {"id": book["entry_id"]}).mappings().one()
    assert row["payee_id"] is None


def test_merge_payees_repoints_entries_and_renames_survivor(book, conn):
    affected = repo.merge_payees(conn, book["acme"]["id"], [book["other"]["id"]], "Merged Co")
    assert affected == 1  # only Acme's own entry
    survivor = next(r for r in repo.payees_all(conn) if r["id"] == book["acme"]["id"])
    assert survivor["name"] == "Merged Co"
    assert not any(r["id"] == book["other"]["id"] for r in repo.payees_all(conn))


def test_merge_payees_returns_none_for_an_unknown_survivor(book, conn):
    assert repo.merge_payees(conn, 999999, [book["other"]["id"]], "X") is None


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def test_tags_all_includes_entry_count(book, conn):
    rows = repo.tags_all(conn)
    food = next(r for r in rows if r["id"] == book["food"]["id"])
    urgent = next(r for r in rows if r["id"] == book["urgent"]["id"])
    assert food["entry_count"] == 1
    assert urgent["entry_count"] == 1


def test_insert_tag(book, conn):
    row = repo.insert_tag(conn, "groceries")
    assert row["name"] == "groceries"


def test_toggle_tag_active_returns_none_for_an_unknown_id(book, conn):
    assert repo.toggle_tag_active(conn, 999999) is None


def test_rename_tag_rowcount(book, conn):
    assert repo.rename_tag(conn, book["food"]["id"], "groceries") == 1
    assert repo.rename_tag(conn, 999999, "nope") == 0


def test_delete_tag_returns_name_or_none(book, conn):
    assert repo.delete_tag(conn, book["urgent"]["id"]) == "urgent"
    assert repo.delete_tag(conn, 999999) is None


def test_merge_tags_repoints_junction_rows_and_renames_survivor(book, conn):
    affected = repo.merge_tags(conn, book["food"]["id"], [book["urgent"]["id"]], "merged-tag")
    assert affected == 1  # only the entry carrying "food"
    survivor = next(r for r in repo.tags_all(conn) if r["id"] == book["food"]["id"])
    assert survivor["name"] == "merged-tag"
    assert not any(r["id"] == book["urgent"]["id"] for r in repo.tags_all(conn))


def test_merge_tags_returns_none_for_an_unknown_survivor(book, conn):
    assert repo.merge_tags(conn, 999999, [book["urgent"]["id"]], "x") is None
