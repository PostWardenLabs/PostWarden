"""The ~450 genuinely-hard report lines: account tree, income statement matrix,
cash flow rows + tie-out, variance, split periods. Phase 1.4 — ported with
comments and docstrings intact, per REBUILD.md §6. Keeps calling the existing
Postgres SRFs (fn_trial_balance, fn_cash_flow_lines, fn_rollup_balance,
fn_account_balances) directly rather than modeling them through SQLAlchemy Core.
"""
