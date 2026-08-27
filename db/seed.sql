-- ============================================================================
-- POSTWARDEN — seed.sql
-- Starter chart of accounts + baseline scenarios. Edit freely: this is a
-- starting point, not a prescription. Codes follow the classic convention:
-- 1xxx assets · 2xxx liabilities · 3xxx equity · 4xxx income · 5xxx+ expenses
--
-- Expenses are split across five sibling top-level accounts (5000-9000)
-- instead of one, following the "Needs vs. Wants" chart-of-accounts pattern
-- in docs/GUIDE.md: 5000 non-negotiable living costs, 6000 discretionary
-- lifestyle spending, 7000 taxes, 8000 debt/financial/professional costs,
-- 9000 gifts and irregular items. See that doc for the full rationale and
-- an alternative "savings-rate-first" pattern, if this one doesn't fit.
-- ============================================================================
BEGIN;

-- Account levels — names the three levels this starter chart actually
-- uses (Assets -> Investment Assets -> Brokerage is 3 deep). Purely
-- labels; add more via the Account levels page if your chart goes
-- deeper than this.
INSERT INTO account_levels (name, depth) VALUES
    ('Top Level Accounts', 1),
    ('Subaccounts',        2),
    ('Account Detail',     3);

-- Scenarios ------------------------------------------------------------------
INSERT INTO scenarios (code, name, scenario_type, enforce_balance, income_statement_only, is_staging, notes) VALUES
    ('ACTUAL',  'Actual',       'actual', TRUE, FALSE, FALSE,
     'The books. Always balanced.'),
    ('BUD2026', 'Budget 2026',  'budget', TRUE, TRUE, FALSE,
     'Annual income/expense budget. No journal entries — edited from the Budget page''s grid.'),
    ('STAGING', 'Staging',      'what_if', TRUE, FALSE, TRUE,
     'A holding pen, not a scenario you post to: entries land here only from a schedule or an import, never typed in directly, and wait on the Staging page for approval into their real target scenario.');

-- Chart of accounts ----------------------------------------------------------
-- Summary (non-postable) parents first, then postable leaves.

-- Assets — 1100 liquid cash, 1200 short-term receivables (money owed *to*
-- you), 1300 investments, 1400 fixed/illiquid. The same four groupings a
-- business chart uses, for the same reason: these behave differently and
-- mature at different times.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('1000', 'Assets', 'asset', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id, is_postable) VALUES
    ('1100', 'Liquid Cash & Cash Equivalents', 'asset', (SELECT id FROM accounts WHERE code = '1000'), FALSE),
    ('1200', 'Short-Term Receivables',         'asset', (SELECT id FROM accounts WHERE code = '1000'), FALSE),
    ('1300', 'Investment Assets',              'asset', (SELECT id FROM accounts WHERE code = '1000'), FALSE),
    ('1400', 'Fixed & Illiquid Assets',        'asset', (SELECT id FROM accounts WHERE code = '1000'), FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('1110', 'Checking',                   'asset', (SELECT id FROM accounts WHERE code = '1100')),
    ('1120', 'Savings',                    'asset', (SELECT id FROM accounts WHERE code = '1100')),
    ('1130', 'Physical Cash',              'asset', (SELECT id FROM accounts WHERE code = '1100')),
    ('1210', 'Money Owed by Friends/Family','asset', (SELECT id FROM accounts WHERE code = '1200')),
    ('1310', 'Brokerage',                  'asset', (SELECT id FROM accounts WHERE code = '1300')),
    ('1320', 'Retirement (401k/IRA/Pension)','asset',(SELECT id FROM accounts WHERE code = '1300')),
    ('1410', 'Vehicles',                   'asset', (SELECT id FROM accounts WHERE code = '1400'));

-- Liabilities
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('2000', 'Liabilities', 'liability', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id, is_postable) VALUES
    ('2100', 'Current Liabilities',   'liability', (SELECT id FROM accounts WHERE code = '2000'), FALSE),
    ('2200', 'Long-Term Liabilities', 'liability', (SELECT id FROM accounts WHERE code = '2000'), FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('2110', 'Credit Cards',              'liability', (SELECT id FROM accounts WHERE code = '2100')),
    ('2210', 'Mortgage',                  'liability', (SELECT id FROM accounts WHERE code = '2200')),
    ('2220', 'Loans (Auto/Student/Personal)', 'liability', (SELECT id FROM accounts WHERE code = '2200'));

-- Equity
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('3000', 'Equity', 'equity', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('3100', 'Opening Balances',            'equity', (SELECT id FROM accounts WHERE code = '3000')),
    ('3200', 'Retained Earnings',           'equity', (SELECT id FROM accounts WHERE code = '3000')),
    ('3300', 'Unrealized Gains/Losses',     'equity', (SELECT id FROM accounts WHERE code = '3000'));

-- Income — kept shallow on purpose; see docs/GUIDE.md's "Should you have
-- more than one Income top-level account?" for when a second one earns
-- its keep (a side business or rental you want to report on separately).
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('4000', 'Income', 'income', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('4100', 'Salary',                    'income', (SELECT id FROM accounts WHERE code = '4000')),
    ('4200', 'Interest & Dividend Income','income', (SELECT id FROM accounts WHERE code = '4000')),
    ('4300', 'Other Income',              'income', (SELECT id FROM accounts WHERE code = '4000'));

-- Expenses — five sibling top-level accounts (not one), each its own
-- account_type='expense' root with no parent, same shape 1000/2000/3000/
-- 4000 use. See the file header and docs/GUIDE.md for why.

-- 5000: Fixed & Essential Living — the "Needs" half of the split.
-- Non-negotiable, hard to reduce short-term.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('5000', 'Fixed & Essential Living', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id, is_postable) VALUES
    ('5100', 'Housing & Utilities', 'expense', (SELECT id FROM accounts WHERE code = '5000'), FALSE),
    ('5300', 'Health & Insurance',  'expense', (SELECT id FROM accounts WHERE code = '5000'), FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('5110', 'Rent / Mortgage Interest', 'expense', (SELECT id FROM accounts WHERE code = '5100')),
    ('5120', 'Utilities',                'expense', (SELECT id FROM accounts WHERE code = '5100')),
    ('5200', 'Transportation',           'expense', (SELECT id FROM accounts WHERE code = '5000')),
    ('5310', 'Insurance',                'expense', (SELECT id FROM accounts WHERE code = '5300')),
    ('5320', 'Medical & Pharmacy',       'expense', (SELECT id FROM accounts WHERE code = '5300')),
    ('5400', 'Groceries',                'expense', (SELECT id FROM accounts WHERE code = '5000'));

-- 6000: Flexible & Lifestyle Expenses — the "Wants" half of the split.
-- The first thing you cut. Note Dining Out lives here, deliberately
-- separate from 5400 Groceries.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('6000', 'Flexible & Lifestyle Expenses', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('6100', 'Dining Out & Coffee',           'expense', (SELECT id FROM accounts WHERE code = '6000')),
    ('6200', 'Entertainment & Subscriptions', 'expense', (SELECT id FROM accounts WHERE code = '6000')),
    ('6300', 'Shopping & Personal Care',      'expense', (SELECT id FROM accounts WHERE code = '6000')),
    ('6400', 'Travel & Vacations',            'expense', (SELECT id FROM accounts WHERE code = '6000'));

-- 7000: Taxes & Mandatory Statutory Deductions — isolated so "actual
-- spendable income" is a real number instead of buried in a paycheck.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('7000', 'Taxes', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('7100', 'Income Tax',    'expense', (SELECT id FROM accounts WHERE code = '7000')),
    ('7200', 'Payroll Taxes', 'expense', (SELECT id FROM accounts WHERE code = '7000'));

-- 8000: Debt, Financial & Professional Costs — the cost of servicing debt
-- and managing money; the debt itself is a liability (2xxx), not this.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('8000', 'Debt, Financial & Professional Costs', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('8100', 'Interest (Credit Card/Loans)',  'expense', (SELECT id FROM accounts WHERE code = '8000')),
    ('8200', 'Banking & Investment Fees',     'expense', (SELECT id FROM accounts WHERE code = '8000')),
    ('8300', 'Professional & Career Development', 'expense', (SELECT id FROM accounts WHERE code = '8000'));

-- 9000: Gifts, Losses & Exceptional Items — irregular/altruistic outflows
-- that would otherwise distort a monthly baseline.
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('9000', 'Gifts, Losses & Exceptional Items', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('9100', 'Charitable Giving',            'expense', (SELECT id FROM accounts WHERE code = '9000')),
    ('9200', 'Gifts to Family/Friends',      'expense', (SELECT id FROM accounts WHERE code = '9000')),
    ('9300', 'Extraordinary/One-off Losses', 'expense', (SELECT id FROM accounts WHERE code = '9000'));

COMMIT;
