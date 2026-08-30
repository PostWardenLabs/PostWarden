"""DB-backed tests of modules.budget.service — the merged/rolled-up grid
`budget_grid` assembles, and `save_budget_cell`'s validation/parsing
ahead of the actual UPSERT."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from postwarden.errors import pg_message
from postwarden.modules.budget import service


def _rows_by_code(result):
    return {r["account_code"]: r for g in result["grouped"] for r in g["rows"]}


def test_budget_grid_leaf_row_has_budgeted_actual_and_variance(book, conn):
    result = service.budget_grid(conn, "BUD", "2026-08-01")
    rent = _rows_by_code(result)["5100"]
    assert rent["budgeted"] == 600
    assert rent["actual"] == 450
    assert rent["variance"] == -150       # actual - budgeted = 450 - 600
    assert rent["pct_variance"] == Decimal("-25.0")  # (450-600)/|600|*100
    assert rent["has_children"] is False


def test_budget_grid_rolls_up_a_subdivided_summary_account(book, conn):
    result = service.budget_grid(conn, "BUD", "2026-08-01")
    other = _rows_by_code(result)["5200"]
    assert other["budgeted"] == 500   # Gas 300 + Electric 200
    assert other["actual"] == 0       # neither has any ACTUAL activity
    assert other["has_children"] is True


def test_budget_grid_quickfill_figures(book, conn):
    result = service.budget_grid(conn, "BUD", "2026-08-01")
    rent = _rows_by_code(result)["5100"]
    assert rent["quickfill"]["last_scenario"] == 300   # July's own budget line
    assert rent["quickfill"]["avg3_scenario"] == 400   # (May 600 + Jun 300 + Jul 300) / 3
    assert rent["quickfill"]["last_actual"] == 0        # no ACTUAL activity in July
    assert rent["quickfill"]["avg3_actual"] == 0        # none in May-July either


def test_budget_grid_returns_zero_stub_for_a_scenario_that_doesnt_exist(book, conn):
    result = service.budget_grid(conn, "NOPE", "2026-08-01")
    assert result["grouped"] == []
    assert result["net_budgeted"] == 0 and result["net_actual"] == 0
    assert result["net_pct_variance"] is None


def test_budget_grid_returns_zero_stub_for_a_full_scenario(book, conn):
    # ACTUAL exists but isn't income-statement-only — same stub as an
    # unknown code, not an error.
    result = service.budget_grid(conn, "ACTUAL", "2026-08-01")
    assert result["grouped"] == []


def test_budget_grid_returns_zero_stub_for_an_empty_scenario(book, conn):
    result = service.budget_grid(conn, "", "2026-08-01")
    assert result["grouped"] == []


def test_save_budget_cell_upserts_and_returns_the_parsed_amount(book, conn):
    amount1 = service.save_budget_cell(
        conn, scenario_id=book["bud"]["id"], account_code="5100",
        period_month=date(2026, 9, 1), amount_raw="150")
    assert amount1 == Decimal("150.00")
    amount2 = service.save_budget_cell(
        conn, scenario_id=book["bud"]["id"], account_code="5100",
        period_month=date(2026, 9, 1), amount_raw="175.50")
    assert amount2 == Decimal("175.50")
    result = service.budget_grid(conn, "BUD", "2026-09-01")
    assert _rows_by_code(result)["5100"]["budgeted"] == Decimal("175.50")


def test_save_budget_cell_defaults_a_blank_amount_to_zero(book, conn):
    amount = service.save_budget_cell(
        conn, scenario_id=book["bud"]["id"], account_code="5100",
        period_month=date(2026, 10, 1), amount_raw="")
    assert amount == Decimal("0.00")


def test_save_budget_cell_rejects_a_non_numeric_amount(book, conn):
    with pytest.raises(ValueError, match="isn't a number"):
        service.save_budget_cell(
            conn, scenario_id=book["bud"]["id"], account_code="5100",
            period_month=date(2026, 8, 1), amount_raw="not-a-number")


def test_save_budget_cell_rejects_an_unknown_account_code(book, conn):
    with pytest.raises(ValueError, match="Unknown account code: NOPE999"):
        service.save_budget_cell(
            conn, scenario_id=book["bud"]["id"], account_code="NOPE999",
            period_month=date(2026, 8, 1), amount_raw="10")


def test_save_budget_cell_surfaces_the_guard_trigger_for_a_full_scenario(book, conn):
    with pytest.raises(SQLAlchemyError) as exc_info:
        service.save_budget_cell(
            conn, scenario_id=book["actual"]["id"], account_code="5100",
            period_month=date(2026, 8, 1), amount_raw="10")
    assert "not income-statement-only" in pg_message(exc_info.value)
