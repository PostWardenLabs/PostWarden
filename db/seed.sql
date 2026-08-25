-- ============================================================================
-- LIBRO — seed.sql
-- Starter chart of accounts + baseline scenarios. Edit freely: this is a
-- starting point, not a prescription. Codes follow the classic convention:
-- 1xxx assets · 2xxx liabilities · 3xxx equity · 4xxx income · 5xxx expenses
-- ============================================================================
BEGIN;

-- Account levels — names the three levels this starter chart actually
-- uses (Assets -> Bank -> Checking is 3 deep). Purely labels; add more
-- via the Account levels page if your chart goes deeper than this.
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

-- Assets
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('1000', 'Assets', 'asset', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id, is_postable) VALUES
    ('1100', 'Bank', 'asset', (SELECT id FROM accounts WHERE code = '1000'), FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('1110', 'Checking',  'asset', (SELECT id FROM accounts WHERE code = '1100')),
    ('1120', 'Savings',   'asset', (SELECT id FROM accounts WHERE code = '1100')),
    ('1200', 'Cash',      'asset', (SELECT id FROM accounts WHERE code = '1000'));

-- Liabilities
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('2000', 'Liabilities', 'liability', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('2100', 'Credit Card', 'liability', (SELECT id FROM accounts WHERE code = '2000'));

-- Equity
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('3000', 'Equity', 'equity', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('3100', 'Opening Balances', 'equity', (SELECT id FROM accounts WHERE code = '3000'));

-- Income
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('4000', 'Income', 'income', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('4100', 'Salary',          'income', (SELECT id FROM accounts WHERE code = '4000')),
    ('4200', 'Interest Income', 'income', (SELECT id FROM accounts WHERE code = '4000'));

-- Expenses
INSERT INTO accounts (code, name, account_type, is_postable) VALUES
    ('5000', 'Expenses', 'expense', FALSE);
INSERT INTO accounts (code, name, account_type, parent_id, is_postable) VALUES
    ('5100', 'Housing', 'expense', (SELECT id FROM accounts WHERE code = '5000'), FALSE),
    ('5200', 'Food',    'expense', (SELECT id FROM accounts WHERE code = '5000'), FALSE);
INSERT INTO accounts (code, name, account_type, parent_id) VALUES
    ('5110', 'Rent',           'expense', (SELECT id FROM accounts WHERE code = '5100')),
    ('5120', 'Utilities',      'expense', (SELECT id FROM accounts WHERE code = '5100')),
    ('5210', 'Groceries',      'expense', (SELECT id FROM accounts WHERE code = '5200')),
    ('5220', 'Dining Out',     'expense', (SELECT id FROM accounts WHERE code = '5200')),
    ('5300', 'Transport',      'expense', (SELECT id FROM accounts WHERE code = '5000')),
    ('5400', 'Health & Fitness','expense',(SELECT id FROM accounts WHERE code = '5000')),
    ('5500', 'Entertainment',  'expense', (SELECT id FROM accounts WHERE code = '5000'));

COMMIT;
