"""Direct tests of modules.budget.repository — one assertion per query,
against the `book` fixture in `conftest.py`. `test_service.py` covers the
merged/rolled-up tree these feed into; this file just confirms each
query returns what its own docstring says."""
from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from postwarden.modules.budget import repository as repo


def test_dim_accounts_is_income_expense_only(book, conn):
    codes = {a["code"] for a in repo.dim_accounts(conn)}
    assert codes == {"5000", "5100", "5200", "5210", "5220"}
    assert "1000" not in codes  # Checking is an asset — never a budget target


def test_income_statement_only_scenario_finds_bud_not_actual(book, conn):
    assert repo.income_statement_only_scenario(conn, "BUD")["id"] == book["bud"]["id"]
    assert repo.income_statement_only_scenario(conn, "ACTUAL") is None
    assert repo.income_statement_only_scenario(conn, "NOPE") is None


def test_account_balances_reads_actual_postings_for_the_month(book, conn):
    # fn_account_balances returns every active account, posted-to or not
    # (see modules.reports.repository.account_balances's own docstring) —
    # Gas/Electric come back as a real 0, not simply absent.
    balances = repo.account_balances(conn, "ACTUAL", "2026-08-31", "2026-08-01")
    assert balances[book["rent"]["id"]] == 450
    assert balances[book["gas"]["id"]] == 0


def test_budget_line_amounts_returns_only_that_months_rows(book, conn):
    amounts = repo.budget_line_amounts(conn, book["bud"]["id"], date(2026, 8, 1))
    assert amounts[book["rent"]["id"]] == 600
    assert amounts[book["gas"]["id"]] == 300
    assert amounts[book["electric"]["id"]] == 200
    july = repo.budget_line_amounts(conn, book["bud"]["id"], date(2026, 7, 1))
    assert july == {book["rent"]["id"]: 300}


def test_budget_line_avg3_averages_the_three_prior_months(book, conn):
    # May 600, June 300, July 300 -> (600+300+300)/3 = 400.
    avg = repo.budget_line_avg3(conn, book["bud"]["id"], date(2026, 5, 1), date(2026, 8, 1))
    assert avg[book["rent"]["id"]] == 400


def test_account_id_by_code(book, conn):
    assert repo.account_id_by_code(conn, "5100") == book["rent"]["id"]
    assert repo.account_id_by_code(conn, "NOPE999") is None


def test_upsert_budget_cell_is_a_real_upsert(book, conn):
    repo.upsert_budget_cell(conn, book["bud"]["id"], book["rent"]["id"], date(2026, 9, 1), 150)
    repo.upsert_budget_cell(conn, book["bud"]["id"], book["rent"]["id"], date(2026, 9, 1), 175.50)
    amounts = repo.budget_line_amounts(conn, book["bud"]["id"], date(2026, 9, 1))
    assert amounts[book["rent"]["id"]] == 175.50


def test_upsert_budget_cell_rejects_a_non_income_statement_only_scenario(book, conn):
    # fn_budget_line_guard fires immediately (not deferred), so this
    # raises right at the INSERT — no COMMIT/SET CONSTRAINTS dance needed.
    with pytest.raises(DBAPIError, match="not income-statement-only"):
        repo.upsert_budget_cell(conn, book["actual"]["id"], book["rent"]["id"], date(2026, 8, 1), 100)
