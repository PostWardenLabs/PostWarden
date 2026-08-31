"""Reports: account tree, income statement matrix, cash flow rows + tie-out,
variance, split periods. Calls the existing Postgres SRFs
(fn_trial_balance, fn_cash_flow_lines, fn_rollup_balance,
fn_account_balances) directly rather than modeling them through
SQLAlchemy Core.
"""
