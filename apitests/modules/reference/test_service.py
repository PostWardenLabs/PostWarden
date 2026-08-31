"""Tests of modules.reference.service — the validation `router.py`
relies on before ever reaching `repository.py`, against the `book`
fixture in `conftest.py`."""
import pytest
from sqlalchemy.exc import DBAPIError

from postwarden.modules.reference import service


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def test_create_account_strips_code_and_name(book, conn):
    row = service.create_account(conn, code=" 1200 ", name=" Savings ", account_type="asset",
                                  parent_id=None, is_postable=True, is_cashflow=False)
    assert row["code"] == "1200"
    assert row["name"] == "Savings"


def test_create_account_surfaces_a_bad_code_as_a_db_error(book, conn):
    with pytest.raises(DBAPIError):
        service.create_account(conn, code="not-a-code", name="Bad", account_type="asset",
                                parent_id=None, is_postable=True, is_cashflow=False)


def test_quick_create_account_requires_a_name(book, conn):
    with pytest.raises(ValueError, match="Name is required"):
        service.quick_create_account(conn, name="  ", parent_id=None, account_type="asset",
                                      is_postable=True)


def test_quick_create_account_inherits_the_parent_type(book, conn):
    row = service.quick_create_account(conn, name="Savings", parent_id=book["assets"]["id"],
                                        account_type=None, is_postable=True)
    assert row["code"].startswith("1")


def test_quick_create_account_rejects_an_unknown_parent(book, conn):
    with pytest.raises(ValueError, match="Unknown parent account"):
        service.quick_create_account(conn, name="Savings", parent_id=999999, account_type=None,
                                      is_postable=True)


def test_quick_create_account_requires_a_type_with_no_parent(book, conn):
    with pytest.raises(ValueError, match="Choose an account type"):
        service.quick_create_account(conn, name="New Top", parent_id=None, account_type=None,
                                      is_postable=True)


def test_toggle_account_active_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Account #999999 not found"):
        service.toggle_account_active(conn, 999999)


def test_toggle_account_cashflow_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Account #999999 not found"):
        service.toggle_account_cashflow(conn, 999999)


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

def test_create_account_level_requires_a_name(book, conn):
    with pytest.raises(ValueError, match="Name is required"):
        service.create_account_level(conn, "  ", 2)


def test_create_account_level_requires_a_positive_depth(book, conn):
    with pytest.raises(ValueError, match="Depth must be a positive number"):
        service.create_account_level(conn, "Subaccounts", 0)


def test_rename_account_level_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Level #999999 not found"):
        service.rename_account_level(conn, 999999, "New Name")


def test_delete_account_level_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Level #999999 not found"):
        service.delete_account_level(conn, 999999)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_create_scenario_upper_cases_the_code(book, conn):
    row = service.create_scenario(conn, code="bud", name="Budget", scenario_type="budget",
                                   enforce_balance=False, income_statement_only=True,
                                   base_level_id=None, notes="  ")
    assert row["code"] == "BUD"


def test_create_scenario_surfaces_the_actual_must_balance_check(book, conn):
    with pytest.raises(DBAPIError):
        service.create_scenario(conn, code="ACTUAL2", name="Actual 2", scenario_type="actual",
                                 enforce_balance=False, income_statement_only=False,
                                 base_level_id=None, notes=None)


def test_toggle_scenario_lock_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Scenario #999999 not found"):
        service.toggle_scenario_lock(conn, 999999)


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

def test_create_payee_requires_a_name(book, conn):
    with pytest.raises(ValueError, match="Payee name is required"):
        service.create_payee(conn, "  ")


def test_rename_payee_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Payee #999999 not found"):
        service.rename_payee(conn, 999999, "New Name")


def test_delete_payee_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Payee #999999 not found"):
        service.delete_payee(conn, 999999)


def test_merge_payees_requires_at_least_two(book, conn):
    with pytest.raises(ValueError, match="at least two payees"):
        service.merge_payees(conn, [book["acme"]["id"]], "X")


def test_merge_payees_requires_a_name(book, conn):
    with pytest.raises(ValueError, match="A name is required"):
        service.merge_payees(conn, [book["acme"]["id"], book["other"]["id"]], "  ")


def test_merge_payees_returns_count_and_affected(book, conn):
    merged, affected = service.merge_payees(
        conn, [book["acme"]["id"], book["other"]["id"]], "Merged Co")
    assert merged == 2
    assert affected == 1


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def test_create_tag_requires_exactly_one_name(book, conn):
    with pytest.raises(ValueError, match="exactly one tag name"):
        service.create_tag(conn, "food, urgent")


def test_create_tag_rejects_an_invalid_name(book, conn):
    with pytest.raises(ValueError, match="Invalid tag"):
        service.create_tag(conn, "N0T VALID!")


def test_rename_tag_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Tag #999999 not found"):
        service.rename_tag(conn, 999999, "groceries")


def test_delete_tag_raises_for_an_unknown_id(book, conn):
    with pytest.raises(ValueError, match="Tag #999999 not found"):
        service.delete_tag(conn, 999999)


def test_merge_tags_requires_at_least_two(book, conn):
    with pytest.raises(ValueError, match="at least two tags"):
        service.merge_tags(conn, [book["food"]["id"]], "x")


def test_merge_tags_returns_count_and_affected(book, conn):
    merged, affected = service.merge_tags(
        conn, [book["food"]["id"], book["urgent"]["id"]], "merged-tag")
    assert merged == 2
    assert affected == 1
