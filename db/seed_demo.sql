-- ============================================================================
-- POSTWARDEN — seed_demo.sql (OPTIONAL)
-- A few sample entries so the first screens aren't empty. Skip this file
-- for a clean start, or delete the database and re-init without it.
-- ============================================================================
BEGIN;

-- Helper CTE-style: look up ids once per statement via subselects.

-- 1. Opening balance ---------------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description, reference)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-01', 'Opening balance', 'OPEN-2026')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
SELECT e.id, x.line_no, x.account_id, x.amount, x.memo FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1110'),  25000.00, 'Checking opening'),
    (2, (SELECT id FROM accounts WHERE code = '1120'),  60000.00, 'Savings opening'),
    (3, (SELECT id FROM accounts WHERE code = '3100'), -85000.00, NULL)
) AS x(line_no, account_id, amount, memo);

-- 2. Salary ------------------------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-14', 'Salary — first half of August')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1110'),  21000.00),
    (2, (SELECT id FROM accounts WHERE code = '4100'), -21000.00)
) AS x(line_no, account_id, amount);

-- 3. Rent paid from checking -------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-05', 'August rent')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5110'),   9500.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),  -9500.00)
) AS x(line_no, account_id, amount);

-- 4. Groceries on the credit card (accrual in action) ------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-09', 'Supermarket run')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5210'),   1850.00),
    (2, (SELECT id FROM accounts WHERE code = '2100'),  -1850.00)
) AS x(line_no, account_id, amount);

-- 5. Credit card payment (liability settled — no expense here) ---------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-18', 'Credit card payment')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '2100'),   1850.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),  -1850.00)
) AS x(line_no, account_id, amount);

-- 6. Budget scenario: income/expense targets in the Budget grid — plain
--    amounts, no journal entries (see budget_lines / scenarios
--    .income_statement_only). amount is always a plain positive target
--    here (unlike journal_lines.amount, there's no debit/credit sign to
--    juggle — a budget number just says how much).
INSERT INTO budget_lines (scenario_id, account_id, period_month, amount) VALUES
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '4100'), DATE '2026-08-01', 21000.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5110'), DATE '2026-08-01',  9500.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5210'), DATE '2026-08-01',  6000.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5220'), DATE '2026-08-01',  2500.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5300'), DATE '2026-08-01',  1800.00),
    -- September too, so the Budget page's prev/next month links have
    -- somewhere to go.
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '4100'), DATE '2026-09-01', 21000.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5110'), DATE '2026-09-01',  9500.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5210'), DATE '2026-09-01',  6200.00);

COMMIT;
