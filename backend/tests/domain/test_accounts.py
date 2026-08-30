"""Unit tests for postwarden.domain.accounts — no database, no app."""
from postwarden.domain.accounts import (
    CURRENT_YEAR_EARNINGS_ID,
    PRIOR_YEAR_EARNINGS_ID,
    RETAINED_EARNINGS_ID,
    accounts_with_gaps,
    build_account_tree,
    earnings_rows,
    flatten_tree,
    income_statement_groups,
    pnl_net,
)

# A small three-level asset tree:
# Assets (1) -> Current Assets (2) -> Checking (3)
ACCOUNTS = [
    {"id": 1, "parent_id": None, "code": "1000", "name": "Assets",
     "parent_path": "", "account_type": "asset", "depth": 0},
    {"id": 2, "parent_id": 1, "code": "1100", "name": "Current Assets",
     "parent_path": "Assets", "account_type": "asset", "depth": 1},
    {"id": 3, "parent_id": 2, "code": "1110", "name": "Checking",
     "parent_path": "Assets > Current Assets", "account_type": "asset", "depth": 2},
]


def test_build_account_tree_rolls_up_descendants_into_subtotal():
    balances = {3: 500}
    roots = build_account_tree(ACCOUNTS, balances)
    assert len(roots) == 1
    assets = roots[0]
    assert assets["net"] == 0  # Assets itself has no direct postings
    assert assets["subtotal"] == 500  # rolled up from Checking
    current = assets["children"][0]
    assert current["subtotal"] == 500
    checking = current["children"][0]
    assert checking["net"] == 500
    assert checking["subtotal"] == 500


def test_build_account_tree_debit_credit_balance_from_sign():
    roots = build_account_tree(ACCOUNTS, {3: -200})
    checking = roots[0]["children"][0]["children"][0]
    assert checking["debit_balance"] == 0
    assert checking["credit_balance"] == 200


def test_build_account_tree_compare_defaults_to_zero_when_absent():
    roots = build_account_tree(ACCOUNTS, {3: 500})
    checking = roots[0]["children"][0]["children"][0]
    assert checking["compare_net"] == 0
    assert checking["compare_subtotal"] == 0


def test_build_account_tree_rolls_up_compare_column_too():
    roots = build_account_tree(ACCOUNTS, {3: 500}, compare_by_id={3: 300})
    assets = roots[0]
    assert assets["compare_subtotal"] == 300


def test_flatten_tree_drops_zero_subtotal_subtree_unless_zeros():
    roots = build_account_tree(ACCOUNTS, {})  # nothing posted anywhere
    assert flatten_tree(roots, zeros=False) == []
    assert len(flatten_tree(roots, zeros=True)) == 3


def test_flatten_tree_keeps_a_row_that_only_moved_on_the_compare_side():
    roots = build_account_tree(ACCOUNTS, {}, compare_by_id={3: 100})
    flat = flatten_tree(roots, zeros=False)
    assert len(flat) == 3  # own side is all zero, but compare side isn't


def test_flatten_tree_sets_has_children_from_survivors_only():
    roots = build_account_tree(ACCOUNTS, {3: 500})
    flat = flatten_tree(roots, zeros=False)
    by_name = {r["account_name"]: r for r in flat}
    assert by_name["Assets"]["has_children"] is True
    assert by_name["Checking"]["has_children"] is False


def test_pnl_net_is_income_minus_expense_sign_corrected():
    accounts = [
        {"id": 1, "account_type": "income"},
        {"id": 2, "account_type": "expense"},
    ]
    # Income is credit-normal (stored negative for real income); expense
    # is debit-normal (stored positive for real expense).
    balances = {1: -300, 2: 100}
    assert pnl_net(accounts, balances) == 200  # 300 income - 100 expense


def test_earnings_rows_builds_a_parent_with_two_real_children():
    rows = earnings_rows(150, -75, zeros=False)
    assert len(rows) == 3
    parent, current, prior = rows
    assert parent["id"] == RETAINED_EARNINGS_ID
    assert parent["parent_id"] is None
    assert parent["has_children"] is True
    assert current["id"] == CURRENT_YEAR_EARNINGS_ID
    assert current["parent_id"] == RETAINED_EARNINGS_ID
    assert prior["id"] == PRIOR_YEAR_EARNINGS_ID
    assert prior["parent_id"] == RETAINED_EARNINGS_ID
    assert current["has_children"] is False
    assert prior["has_children"] is False


def test_earnings_rows_shapes_amount_into_debit_credit_columns():
    _, current, prior = earnings_rows(150, -75, zeros=False)
    assert current["debit_balance"] == 0
    assert current["credit_balance"] == 150
    assert prior["debit_balance"] == 75
    assert prior["credit_balance"] == 0


def test_earnings_rows_subtotal_is_negated_for_the_shared_equity_sign_flip():
    # `subtotal` mirrors a real Equity account's own "credit-normal,
    # negative internally" storage convention, not `pnl_net`'s "positive
    # means real earnings" one — so the same -1 sign flip every real
    # Equity row already gets (Balance Sheet's own per-section sign,
    # the CSV/XLSX exporters' own `-r["subtotal"]`) also turns this back
    # into the correct positive-for-profit figure with no special case.
    parent, current, prior = earnings_rows(150, -75, zeros=False)
    assert parent["subtotal"] == -75  # -(150 + -75)
    assert current["subtotal"] == -150
    assert prior["subtotal"] == 75


def test_earnings_rows_all_or_nothing_on_zero_unless_zeros_flag():
    assert earnings_rows(0, 0, zeros=False) == []
    assert len(earnings_rows(0, 0, zeros=True)) == 3
    # Only one side zero still returns the full parent+children triple —
    # not just the nonzero child — since they're one collapsible unit now.
    assert len(earnings_rows(100, 0, zeros=False)) == 3


def test_accounts_with_gaps_interleaves_a_gap_before_each_row_and_one_trailing():
    accounts = [{"id": 1}, {"id": 2}]
    rows = accounts_with_gaps(accounts)
    kinds = [r["kind"] for r in rows]
    assert kinds == ["gap", "account", "gap", "account", "gap"]
    assert rows[0]["track_id"] == 1
    assert rows[2]["track_id"] == 2
    assert rows[-1]["track_id"] == 2  # trailing gap tracks the last account


def test_accounts_with_gaps_handles_empty_list():
    rows = accounts_with_gaps([])
    assert rows == [{"kind": "gap", "track_id": None}]


# Two-root income/expense tree — same shape _income_statement_rows feeds
# income_statement_groups (a build_account_tree() result restricted to one
# account_type at a time).
INCOME_EXPENSE_ACCOUNTS = [
    {"id": 10, "parent_id": None, "code": "4000", "name": "Income",
     "parent_path": "", "account_type": "income", "depth": 0},
    {"id": 11, "parent_id": 10, "code": "4100", "name": "Salary",
     "parent_path": "Income", "account_type": "income", "depth": 1},
    {"id": 20, "parent_id": None, "code": "5000", "name": "Expenses",
     "parent_path": "", "account_type": "expense", "depth": 0},
    {"id": 21, "parent_id": 20, "code": "5100", "name": "Rent",
     "parent_path": "Expenses", "account_type": "expense", "depth": 1},
]


def test_income_statement_groups_flips_credit_normal_income_to_positive():
    # Income posts negative (credit-normal); flip=True makes it read as a
    # plain positive figure, same as expense (debit-normal) already does.
    roots = build_account_tree(INCOME_EXPENSE_ACCOUNTS, {11: -1000, 21: 400})
    income = income_statement_groups(roots, "income", flip=True, zeros=False)
    expense = income_statement_groups(roots, "expense", flip=False, zeros=False)
    assert income[0]["base_subtotal"] == 1000
    assert expense[0]["base_subtotal"] == 400


def test_income_statement_groups_computes_variance_against_compare_column():
    roots = build_account_tree(INCOME_EXPENSE_ACCOUNTS, {11: -1000, 21: 400},
                                compare_by_id={11: -800, 21: 300})
    income = income_statement_groups(roots, "income", flip=True, zeros=False)
    g = income[0]
    assert g["compare_subtotal"] == 800
    assert g["variance"] == 200  # 1000 - 800
    assert g["pct_variance"] == 25.0  # (1000-800)/800 * 100
    row = g["rows"][0]  # the root row itself (Income has_children in flatten_tree)
    assert row["base_net"] == 1000
    assert row["variance"] == 200


def test_income_statement_groups_hides_zero_root_unless_zeros():
    roots = build_account_tree(INCOME_EXPENSE_ACCOUNTS, {21: 400})  # no income activity
    assert income_statement_groups(roots, "income", flip=True, zeros=False) == []
    assert len(income_statement_groups(roots, "income", flip=True, zeros=True)) == 1


def test_income_statement_groups_sign_never_produces_negative_zero():
    # A genuinely zero income root, flipped (sign=-1 * 0), must render as
    # 0 not -0 — normalize_zero's whole reason for existing (see its own
    # docstring: this was legacy's duplicate inline `signed()` guard).
    roots = build_account_tree(INCOME_EXPENSE_ACCOUNTS, {11: 0, 21: 400})
    income = income_statement_groups(roots, "income", flip=True, zeros=True)
    assert str(income[0]["base_subtotal"]) != "-0"
    assert income[0]["base_subtotal"] == 0
