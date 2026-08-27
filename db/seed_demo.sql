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
    (1, (SELECT id FROM accounts WHERE code = '5400'),   1850.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),  -1850.00)
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
    (1, (SELECT id FROM accounts WHERE code = '2110'),   1850.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),  -1850.00)
) AS x(line_no, account_id, amount);

-- 6. ATM withdrawal — pocket cash -------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-02', 'ATM withdrawal')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1130'),    100.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -100.00)
) AS x(line_no, account_id, amount);

-- 7. Loaned money to a friend (a receivable, not an expense) -----------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-03', 'Loaned money to a friend')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1210'),    300.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -300.00)
) AS x(line_no, account_id, amount);

-- 8. Investing — cash moves into the brokerage and a 401(k) contribution ----
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-04', 'Transfer to brokerage')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1310'),   5000.00),
    (2, (SELECT id FROM accounts WHERE code = '1120'),  -5000.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-04', '401(k) contribution')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1320'),   1000.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),  -1000.00)
) AS x(line_no, account_id, amount);

-- 9. Utilities --------------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-06', 'August utilities')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5120'),    165.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -165.00)
) AS x(line_no, account_id, amount);

-- 10. Bought a used car — a fixed asset, financed with a loan ---------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-07', 'Bought a used car')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1410'),  12000.00),
    (2, (SELECT id FROM accounts WHERE code = '2220'), -12000.00)
) AS x(line_no, account_id, amount);

-- 11. Transportation + Insurance --------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-08', 'Gas fill-up')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5200'),     55.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),    -55.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-08', 'Auto insurance premium')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5310'),    140.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -140.00)
) AS x(line_no, account_id, amount);

-- 12. Dining Out + a subscription -------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-10', 'Dinner out')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '6100'),     85.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),    -85.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-10', 'Streaming subscription')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '6200'),     15.99),
    (2, (SELECT id FROM accounts WHERE code = '1110'),    -15.99)
) AS x(line_no, account_id, amount);

-- 13. Pharmacy copay ---------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-11', 'Pharmacy copay')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '5320'),     25.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),    -25.00)
) AS x(line_no, account_id, amount);

-- 14. Side income received — a second Income leaf, not Salary -----------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-12', 'Side project payment received')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1110'),    500.00),
    (2, (SELECT id FROM accounts WHERE code = '4300'),   -500.00)
) AS x(line_no, account_id, amount);

-- 15. Shopping + a weekend trip ----------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-13', 'New shoes')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '6300'),     90.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),    -90.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-15', 'Weekend trip lodging')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '6400'),    350.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),   -350.00)
) AS x(line_no, account_id, amount);

-- 16. Auto loan payment (principal only, kept simple) --------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-19', 'Auto loan payment')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '2220'),    400.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -400.00)
) AS x(line_no, account_id, amount);

-- 17. Banking fee + professional development (Debt/Financial/Professional) ----
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-21', 'ATM fee (out-of-network)')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '8200'),      4.50),
    (2, (SELECT id FROM accounts WHERE code = '1110'),     -4.50)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-22', 'Certification renewal fee')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '8300'),    150.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -150.00)
) AS x(line_no, account_id, amount);

-- 18. Charitable donation + a birthday gift (Gifts, Losses & Exceptional) -----
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-23', 'Donation')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '9100'),    100.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -100.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-24', 'Birthday gift')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '9200'),     75.00),
    (2, (SELECT id FROM accounts WHERE code = '2110'),    -75.00)
) AS x(line_no, account_id, amount);

-- 19. Phone lost, uninsured — an extraordinary/one-off loss --------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-25', 'Phone lost, uninsured')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '9300'),    300.00),
    (2, (SELECT id FROM accounts WHERE code = '1110'),   -300.00)
) AS x(line_no, account_id, amount);

-- 20. Salary — second half of August, this time with taxes withheld, to show
--     7000's two leaves the way a real paycheck actually looks -------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-28', 'Salary — second half of August')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1110'),  16500.00),
    (2, (SELECT id FROM accounts WHERE code = '7100'),   3000.00),
    (3, (SELECT id FROM accounts WHERE code = '7200'),   1500.00),
    (4, (SELECT id FROM accounts WHERE code = '4100'), -21000.00)
) AS x(line_no, account_id, amount);

-- 21. Month-end: interest earned, a brokerage mark-to-market gain, and the
--     card's own interest charge — all naturally land at the statement/
--     period close ------------------------------------------------------------
WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-31', 'Interest earned on savings')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1120'),     45.00),
    (2, (SELECT id FROM accounts WHERE code = '4200'),    -45.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-31', 'Brokerage — market value adjustment')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '1310'),    150.00),
    (2, (SELECT id FROM accounts WHERE code = '3300'),   -150.00)
) AS x(line_no, account_id, amount);

WITH e AS (
    INSERT INTO journal_entries (scenario_id, entry_date, description)
    VALUES ((SELECT id FROM scenarios WHERE code = 'ACTUAL'),
            DATE '2026-08-31', 'Credit card interest charge')
    RETURNING id
)
INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
SELECT e.id, x.line_no, x.account_id, x.amount FROM e, (VALUES
    (1, (SELECT id FROM accounts WHERE code = '8100'),     22.50),
    (2, (SELECT id FROM accounts WHERE code = '2110'),    -22.50)
) AS x(line_no, account_id, amount);

-- Not demoed: 2210 Mortgage and 3200 Retained Earnings. A mortgage needs a
-- matching home-value asset to avoid an artificially deep negative net
-- worth in the demo, and this starter chart deliberately doesn't seed one
-- (see docs/GUIDE.md); Retained Earnings is normally populated by an
-- actual close, which this app never posts for real (SPEC.md decision
-- 10 — the close is a query, not a posting), so a hand-posted balance
-- there would misrepresent how the account is meant to get its number.

-- 22. Budget scenario: income/expense targets in the Budget grid — plain
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
     (SELECT id FROM accounts WHERE code = '5400'), DATE '2026-08-01',  6000.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '6100'), DATE '2026-08-01',  2500.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5200'), DATE '2026-08-01',  1800.00),
    -- September too, so the Budget page's prev/next month links have
    -- somewhere to go.
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '4100'), DATE '2026-09-01', 21000.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5110'), DATE '2026-09-01',  9500.00),
    ((SELECT id FROM scenarios WHERE code = 'BUD2026'),
     (SELECT id FROM accounts WHERE code = '5400'), DATE '2026-09-01',  6200.00);

COMMIT;
