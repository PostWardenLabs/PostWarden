"""DB-backed tests of modules.reports.service — the report-assembly
functions REBUILD.md §6 calls the ~450 "genuinely hard" lines, run
against a real Postgres (see ../../conftest.py and this package's own
conftest.py for the `book` fixture the numbers below are hand-derived
from). Each report's own pure sub-logic (sign flips, zero-hiding, tree
rollup) already has dedicated, DB-free coverage in tests/domain/ — these
tests prove the SQL wiring and assembly glue instead: right SRF args,
right column names, right sign conventions, numbers that actually
reconcile against each other."""
from decimal import Decimal

from postwarden.modules.reports import service

from ...conftest import mk_account_level, mk_entry, mk_line, mk_scenario


def test_trial_balance_raw_is_in_balance(book, conn):
    # raw=1: every account at its own all-time balance, no earnings
    # split. Debits (Checking 2200 + Rent 800) == Credits (OBE 1000 +
    # Salary 2000) == 3000 — the plain double-entry identity.
    result = service.trial_balance(conn, "ACTUAL", "2026-02-28", zeros=0, raw=1)
    assert result["total_debits"] == Decimal("3000.00")
    assert result["total_credits"] == Decimal("3000.00")
    assert result["in_balance"] is True


def test_trial_balance_splits_current_and_prior_year_earnings(book, conn):
    # fy_start=2026-01-01 covers all three entries (same as all-time here,
    # since the book has nothing before 2026) -> prior_year_earnings == 0.
    # month_start=2026-02-01 covers only the Feb entries -> mtd_earnings
    # == fy_earnings == 1200 (2000 salary - 800 rent) -> current_year == 0
    # too, so with zeros=0 (default) neither synthetic row appears.
    result = service.trial_balance(conn, "ACTUAL", "2026-02-28", zeros=0, raw=0)
    equity_rows = next(g for g in result["grouped"] if g["type"] == "equity")["rows"]
    assert not any("Earnings" in r["account_name"] for r in equity_rows)

    # zeros=1 forces both synthetic rows to show even at $0.
    result_zeros = service.trial_balance(conn, "ACTUAL", "2026-02-28", zeros=1, raw=0)
    equity_rows_zeros = next(g for g in result_zeros["grouped"] if g["type"] == "equity")["rows"]
    assert sum(1 for r in equity_rows_zeros if "Earnings" in r["account_name"]) == 2


def test_balance_sheet_balances(book, conn):
    # Assets (Checking 2200) == Liabilities (0) + Equity (OBE -1000,
    # sign-flipped to 1000 by -sum(subtotal)) + P&L (1200 unclosed
    # earnings) = 1000 + 1200 = 2200.
    result = service.balance_sheet(conn, "ACTUAL", "2026-02-28")
    assert result["total_assets"] == Decimal("2200.00")
    assert result["total_liab_and_equity"] == Decimal("2200.00")
    assert result["in_balance"] is True


def test_income_statement_rows_net_income_for_february(book, conn):
    # Feb-only: Salary 2000 (flipped positive) - Rent 800 = 1200 net income.
    result = service.income_statement_rows(conn, "ACTUAL", "2026-02-01", "2026-02-28")
    assert result["total_base_income"] == Decimal("2000.00")
    assert result["net_income"] == Decimal("1200.00")


def test_income_statement_matrix_totals_column_matches_unsplit_range(book, conn):
    from postwarden.domain.periods import split_periods
    periods = split_periods("2026-01-01", "2026-02-28", "monthly")
    matrix = service.income_statement_matrix(conn, "ACTUAL", periods, "2026-01-01", "2026-02-28")
    # Totals is periods_totals[-2] (Average is [-1]) — see the function's
    # own docstring on why Totals/Average are appended, not folded in.
    totals = matrix["periods_totals"][-2]
    average = matrix["periods_totals"][-1]
    unsplit = service.income_statement_rows(conn, "ACTUAL", "2026-01-01", "2026-02-28")
    assert totals["net_income"] == unsplit["net_income"] == Decimal("1200.00")
    # Average == Totals / 2 real periods (Jan, Feb) exactly — scale_income_
    # statement_result's whole reason for existing (see its own docstring).
    assert average["net_income"] == Decimal("600.00")


def test_cash_flow_rows_ties_out(book, conn):
    # Inflows: Salary 2000. Outflows: Rent -800. Ledger adjustments:
    # Opening Balance Equity +1000 (equity-contra, rule 1). Net change =
    # 2000 - 800 + 1000 = 2200, matching Checking's own postings exactly
    # (it's the only is_cashflow account) — the tie-out's whole point.
    result = service.cash_flow_rows(conn, "ACTUAL", "2026-01-01", "2026-02-28")
    assert result["total_inflows"] == Decimal("2000.00")
    assert result["total_outflows"] == Decimal("-800.00")
    assert result["total_adjustments"] == Decimal("1000.00")
    assert result["net_change"] == Decimal("2200.00")
    assert result["tie_out"]["ok"] is True
    assert result["tie_out"]["beginning"] == Decimal("0.00")
    assert result["tie_out"]["ending"] == Decimal("2200.00")
    assert result["flagged_entries"] == []  # no entry here has >1 cash leg


def test_compute_variance_native_depth_total_baseline_is_zero(book, conn):
    # A single self-consistent scenario's own accounts always net to zero
    # (assets + equity + income + expense, unsigned) — the same identity
    # trial_balance's in_balance check verifies from the debit/credit
    # side; compute_variance's own total_baseline is a different
    # aggregation of the exact same fact.
    result = service.compute_variance(conn, "ACTUAL", "", "", "2026-02-28")
    assert result["rolled_up"] is False
    assert result["total_baseline"] == Decimal("0.00")
    assert result["compare"] == ""  # no other full scenario to default to


def test_compute_variance_rolled_up_to_a_chosen_level(book, conn):
    """A second, coarser scenario (BUDGET, posting straight to the
    summary "Assets" account via base_level_id) rolled up against
    ACTUAL's own leaf-level Checking postings — the one mode
    fn_rollup_balance exists for (see its own comment in schema.sql).
    v_dim_account depth is 1-indexed (root = 1 — see the view's own
    definition), so "Assets" (root) sits at depth 1; account_levels.depth
    has its own `CHECK (depth > 0)`, consistent with that."""
    level = mk_account_level(conn, "Top level", depth=1)
    budget = mk_scenario(conn, "BUDGET", scenario_type="budget", base_level_id=level["id"])
    e = mk_entry(conn, budget["id"], "2026-02-01", "Budgeted opening")
    mk_line(conn, e, book["assets"]["id"], 600, 1)
    mk_line(conn, e, book["equity"]["id"], -600, 2)

    result = service.compute_variance(conn, "ACTUAL", "BUDGET", "", "2026-02-28")
    assert result["rolled_up"] is True
    assert result["level_id"] == str(level["id"])
    assets_row = next(r for r in result["merged"] if r["account_code"] == "1000")
    # ACTUAL's Checking postings (2200) rolled up onto Assets (depth 1);
    # BUDGET posted 600 straight to Assets itself.
    assert assets_row["baseline_net"] == Decimal("2200.00")
    assert assets_row["compare_net"] == Decimal("600.00")
