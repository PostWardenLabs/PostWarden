"""Direct tests of modules.reports.repository — proves the raw SQL/SRF
wiring against a real Postgres (schema.sql applied, no seed data
assumed; see ../../conftest.py). Not exhaustive: the report-assembly
edge cases (zero-hiding, sign flips, tie-out) are already covered either
by domain/ unit tests (the pure parts) or test_service.py (the DB-backed
assembly) — this file just proves each repository function returns what
its own docstring says it does."""
from decimal import Decimal

from postwarden.modules.reports import repository as repo
from ...conftest import mk_budget_line, mk_scenario


def test_dim_accounts_orders_parent_before_child(book, conn):
    accounts = repo.dim_accounts(conn)
    codes = [a["code"] for a in accounts]
    assert codes.index("1000") < codes.index("1100")  # Assets before Checking


def test_dim_accounts_income_expense_only_filters_out_asset_and_equity(book, conn):
    accounts = repo.dim_accounts(conn, income_expense_only=True)
    types = {a["account_type"] for a in accounts}
    assert types == {"income", "expense"}


def test_account_balances_uses_journal_sign_convention(book, conn):
    # Checking (asset, debit-normal): 1000 + 2000 - 800 = 2200.
    # Salary (income, credit-normal): stored negative.
    balances = repo.account_balances(conn, "ACTUAL", "2026-02-28")
    assert balances[book["checking"]["id"]] == Decimal("2200.00")
    assert balances[book["salary"]["id"]] == Decimal("-2000.00")


def test_account_balances_since_scopes_to_a_window(book, conn):
    # since=2026-02-01 excludes the Jan 15 opening-balance entry: Checking's
    # February-only activity is +2000 (paycheck) - 800 (rent) = 1200, not
    # the all-time 2200 test_account_balances_uses_journal_sign_convention
    # asserts.
    balances = repo.account_balances(conn, "ACTUAL", "2026-02-28", "2026-02-01")
    assert balances[book["checking"]["id"]] == Decimal("1200.00")


def test_account_balances_unknown_scenario_returns_every_account_at_zero(book, conn):
    # fn_account_balances LEFT JOINs from v_dim_account, so an unknown
    # scenario code still returns one row per active account — just with
    # nothing joined in, net=0 — not an empty result set.
    balances = repo.account_balances(conn, "NOPE", None)
    assert balances[book["checking"]["id"]] == Decimal("0.00")


def test_cash_flow_lines_sign_flips_the_non_cash_leg(book, conn):
    lines = repo.cash_flow_lines(conn, "ACTUAL", "2026-02-01", "2026-02-28")
    by_account = {l["contra_account_id"]: l for l in lines}
    # Rent posted +800 (debit); its cash-flow row is the flip: -800 (an outflow).
    assert by_account[book["rent"]["id"]]["amount"] == Decimal("-800.00")
    assert by_account[book["rent"]["id"]]["n_cash_legs"] == 1


def test_scenario_by_code_returns_none_for_unknown_code(conn):
    assert repo.scenario_by_code(conn, "NOPE") is None


def test_scenario_by_code_returns_income_statement_only_flag(book, conn):
    scen = repo.scenario_by_code(conn, "ACTUAL")
    assert scen["income_statement_only"] is False


def test_full_scenarios_lists_code_and_flags_only(book, conn):
    scens = repo.full_scenarios(conn)
    assert scens == [{"code": "ACTUAL", "income_statement_only": False, "is_staging": False}]


def test_postable_flags_reflects_summary_vs_leaf(book, conn):
    flags = repo.postable_flags(conn)
    assert flags[book["assets"]["id"]] is False  # summary account
    assert flags[book["checking"]["id"]] is True  # leaf


def test_ledger_accounts_excludes_summary_accounts(book, conn):
    accounts = repo.ledger_accounts(conn)
    codes = {a["code"] for a in accounts}
    assert book["checking"]["id"] in {a["id"] for a in accounts}
    assert "1000" not in codes  # Assets — summary, not postable


def test_ledger_accounts_orders_by_type_then_code(book, conn):
    accounts = repo.ledger_accounts(conn)
    codes = [a["code"] for a in accounts]
    # asset (1100) < equity (3100) < income (4100) < expense (5100),
    # same ACCOUNT_TYPES order every other report groups by.
    assert codes.index("1100") < codes.index("3100") < codes.index("4100") < codes.index("5100")


def test_ledger_lines_itemizes_each_line_not_a_balance(book, conn):
    lines = repo.ledger_lines(conn, "ACTUAL", "2026-02-28")
    checking_lines = [ln for ln in lines if ln["account_id"] == book["checking"]["id"]]
    # Three lines actually posted to Checking (Opening balance, Paycheck,
    # Rent payment) — three separate rows, not one summed balance.
    assert len(checking_lines) == 3
    assert {ln["entry_date"].isoformat() for ln in checking_lines} == {"2026-01-15", "2026-02-01", "2026-02-05"}


def test_ledger_lines_respects_as_of_upper_bound(book, conn):
    lines = repo.ledger_lines(conn, "ACTUAL", "2026-01-31")
    # Only the Jan 15 opening-balance entry is on or before this as_of —
    # the Feb 1/5 entries are excluded, same "<=" bound every point-in-
    # time report's own as_of already uses.
    assert {ln["entry_date"].isoformat() for ln in lines} == {"2026-01-15"}


def test_budget_line_totals_with_both_date_bounds_set(book, conn):
    # Regression test for a real bug found building Income Statement:
    # `:date_from::date` (a bind param directly
    # followed by Postgres's `::` cast, no space) reads to SQLAlchemy's
    # text() parser as something other than a plain named param, so the
    # literal string reached Postgres unsubstituted and raised a syntax
    # error — but only when *both* date_from and date_to are set (the
    # only shape that hits both `where.append(...)` branches at once).
    # No test exercised this before; `budget_line_totals` had none of its
    # own at all.
    budget = mk_scenario(conn, "BUD", scenario_type="budget", income_statement_only=True)
    mk_budget_line(conn, budget["id"], book["salary"]["id"], -500, "2026-02-01")
    mk_budget_line(conn, budget["id"], book["salary"]["id"], -500, "2026-03-01")
    totals = repo.budget_line_totals(conn, budget["id"], "2026-02-01", "2026-02-28")
    assert totals == {book["salary"]["id"]: Decimal("-500.00")}
