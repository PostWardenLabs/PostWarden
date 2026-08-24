-- ============================================================================
-- LIBRO — seed.sql
-- Starter chart of accounts + baseline scenarios. Edit freely: this is a
-- starting point, not a prescription. Codes follow the classic convention:
-- 1xxx assets · 2xxx liabilities · 3xxx equity · 4xxx income · 5xxx expenses
-- ============================================================================
BEGIN;

-- Scenarios ------------------------------------------------------------------
INSERT INTO scenarios (code, name, scenario_type, enforce_balance, notes) VALUES
    ('ACTUAL',  'Actual',       'actual', TRUE,
     'The books. Always balanced.'),
    ('BUD2026', 'Budget 2026',  'budget', FALSE,
     'Annual budget. Single-sided planning entries allowed (CPM-style input).'),
    ('STAGING', 'Staging',      'what_if', TRUE,
     'Auto-posted by Scheduled entries, awaiting approval. Never counts as real books until promoted.');

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
