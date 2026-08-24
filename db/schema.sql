-- ============================================================================
-- LIBRO — a personal general ledger with scenarios
-- schema.sql — source of truth for the data model
--
-- Design principles:
--   1. The database, not the application, guarantees double-entry integrity.
--      (GnuCash enforces balance in C++; we enforce it with a deferred
--      constraint trigger so *no* client can commit an unbalanced entry.)
--   2. Signed amounts are canonical: debit = positive, credit = negative.
--      The double-entry invariant is then simply SUM(amount) = 0 per entry.
--      debit/credit presentation columns are GENERATED from amount.
--   3. Scenario is a dimension of the fact, not a separate module
--      (the OneStream model). ACTUAL, budgets and forecasts are all just
--      journal entries tagged with a scenario. Variance is a query.
--   4. Journal lines are immutable. Mistakes are fixed by posting a
--      reversing entry, never by editing history.
--   5. Every relationship is a real FOREIGN KEY. No slots table. No GUIDs.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Enumerated types
-- ---------------------------------------------------------------------------
CREATE TYPE account_type AS ENUM ('asset', 'liability', 'equity', 'income', 'expense');
CREATE TYPE scenario_type AS ENUM ('actual', 'budget', 'forecast', 'what_if');

-- ---------------------------------------------------------------------------
-- Scenarios (the OneStream-style dimension)
--
-- enforce_balance:
--   TRUE  -> entries in this scenario must balance (SUM(amount)=0). Always
--            true for ACTUAL. Also true if you want a *rigorous* budget:
--            a fully articulated projected P&L + balance sheet.
--   FALSE -> single-sided planning entries allowed (CPM-style budget input:
--            "Groceries 6,000 in March" with no counter-account).
-- is_locked: no new entries may be posted while locked (enforced by trigger).
-- ---------------------------------------------------------------------------
CREATE TABLE scenarios (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE
                    CHECK (code = upper(code) AND code ~ '^[A-Z0-9_]{2,24}$'),
    name            TEXT NOT NULL,
    scenario_type   scenario_type NOT NULL,
    enforce_balance BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked       BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The ACTUAL scenario must always enforce balance: your books are your books.
ALTER TABLE scenarios ADD CONSTRAINT actual_must_balance
    CHECK (NOT (scenario_type = 'actual' AND enforce_balance = FALSE));

-- ---------------------------------------------------------------------------
-- Chart of accounts (hierarchical)
--
-- is_postable: only leaf accounts take journal lines; summary accounts
-- exist to structure the chart and roll up in reports.
-- normal_side is derivable from account_type (assets/expenses are debit-
-- normal; liabilities/equity/income are credit-normal) — see v_dim_account.
-- ---------------------------------------------------------------------------
CREATE TABLE accounts (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE
                 CHECK (code ~ '^[0-9]{3,8}$'),
    name         TEXT NOT NULL CHECK (length(trim(name)) > 0),
    account_type account_type NOT NULL,
    parent_id    BIGINT REFERENCES accounts(id) ON DELETE RESTRICT,
    is_postable  BOOLEAN NOT NULL DEFAULT TRUE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    currency     CHAR(3) NOT NULL DEFAULT 'MXN',
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE INDEX idx_accounts_parent ON accounts(parent_id);

-- Hierarchy integrity: a child must share its parent's account_type
-- (no Expense children under Assets), and the parent chain must be acyclic.
CREATE OR REPLACE FUNCTION fn_account_hierarchy_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_parent_type account_type;
    v_cursor      BIGINT;
    v_depth       INT := 0;
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        SELECT account_type INTO v_parent_type
          FROM accounts WHERE id = NEW.parent_id;
        IF v_parent_type IS DISTINCT FROM NEW.account_type THEN
            RAISE EXCEPTION
                'Account % (%) must have the same type as its parent (% vs %)',
                NEW.code, NEW.name, NEW.account_type, v_parent_type;
        END IF;
        -- walk up to detect cycles
        v_cursor := NEW.parent_id;
        WHILE v_cursor IS NOT NULL LOOP
            v_depth := v_depth + 1;
            IF v_cursor = NEW.id OR v_depth > 50 THEN
                RAISE EXCEPTION
                    'Account hierarchy cycle or excessive depth at account %', NEW.code;
            END IF;
            SELECT parent_id INTO v_cursor FROM accounts WHERE id = v_cursor;
        END LOOP;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_account_hierarchy_guard
BEFORE INSERT OR UPDATE OF parent_id, account_type ON accounts
FOR EACH ROW EXECUTE FUNCTION fn_account_hierarchy_guard();

-- ---------------------------------------------------------------------------
-- Journal entries (header) and journal lines (the fact table)
-- ---------------------------------------------------------------------------
CREATE TABLE journal_entries (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_id        BIGINT NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
    entry_date         DATE NOT NULL,
    description        TEXT NOT NULL CHECK (length(trim(description)) > 0),
    reference          TEXT,
    reverses_entry_id  BIGINT REFERENCES journal_entries(id) ON DELETE RESTRICT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reverses_entry_id <> id)
);

CREATE INDEX idx_entries_scenario_date ON journal_entries(scenario_id, entry_date);

-- An entry may be reversed at most once. This is also the invariant the app
-- relies on to show "reversed by #N" and to refuse a second Reverse click —
-- enforcing it here (not just in app.py) closes the race where two
-- concurrent reversal requests could otherwise both succeed.
CREATE UNIQUE INDEX uq_one_reversal_per_entry
    ON journal_entries (reverses_entry_id) WHERE reverses_entry_id IS NOT NULL;

CREATE TABLE journal_lines (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id   BIGINT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    line_no    SMALLINT NOT NULL CHECK (line_no > 0),
    account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    -- Canonical signed amount: debit > 0, credit < 0. Never zero.
    amount     NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    -- Presentation columns, derived — you can never store an inconsistent pair.
    debit      NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
               (CASE WHEN amount > 0 THEN amount ELSE 0 END) STORED,
    credit     NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
               (CASE WHEN amount < 0 THEN -amount ELSE 0 END) STORED,
    memo       TEXT,
    UNIQUE (entry_id, line_no)
);

CREATE INDEX idx_lines_entry   ON journal_lines(entry_id);
CREATE INDEX idx_lines_account ON journal_lines(account_id);

-- ---------------------------------------------------------------------------
-- Integrity trigger 1 — THE double-entry invariant, enforced at COMMIT.
--
-- A deferred constraint trigger lets the application insert the header and
-- all lines inside one transaction; only when it tries to COMMIT does
-- PostgreSQL verify every touched entry balances (when its scenario says so)
-- and has at least one line. There is no code path around this.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_entry_balanced() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_entry_id   BIGINT;
    v_sum        NUMERIC(18,2);
    v_line_count INT;
    v_enforce    BOOLEAN;
    v_scenario   TEXT;
BEGIN
    IF TG_TABLE_NAME = 'journal_entries' THEN
        v_entry_id := NEW.id;
    ELSE
        v_entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
    END IF;

    -- Entry may have been deleted in the same transaction; nothing to check.
    IF NOT EXISTS (SELECT 1 FROM journal_entries WHERE id = v_entry_id) THEN
        RETURN NULL;
    END IF;

    SELECT s.enforce_balance, s.code INTO v_enforce, v_scenario
      FROM journal_entries e
      JOIN scenarios s ON s.id = e.scenario_id
     WHERE e.id = v_entry_id;

    SELECT COALESCE(SUM(amount), 0), COUNT(*) INTO v_sum, v_line_count
      FROM journal_lines WHERE entry_id = v_entry_id;

    IF v_line_count = 0 THEN
        RAISE EXCEPTION 'Journal entry % has no lines', v_entry_id;
    END IF;

    IF v_enforce AND v_sum <> 0 THEN
        RAISE EXCEPTION
            'Journal entry % is not balanced: debits - credits = % (scenario % enforces balance)',
            v_entry_id, v_sum, v_scenario;
    END IF;

    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_lines_balanced
AFTER INSERT OR UPDATE OR DELETE ON journal_lines
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_entry_balanced();

CREATE CONSTRAINT TRIGGER trg_entry_has_lines
AFTER INSERT ON journal_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_entry_balanced();

-- ---------------------------------------------------------------------------
-- Integrity trigger 2 — lines may only hit postable, active accounts.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_line_account_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_postable BOOLEAN;
    v_active   BOOLEAN;
    v_code     TEXT;
    v_name     TEXT;
BEGIN
    SELECT is_postable, is_active, code, name
      INTO v_postable, v_active, v_code, v_name
      FROM accounts WHERE id = NEW.account_id;

    IF NOT v_postable THEN
        RAISE EXCEPTION
            'Account % — % is a summary account; post to a leaf account instead',
            v_code, v_name;
    END IF;
    IF NOT v_active THEN
        RAISE EXCEPTION 'Account % — % is inactive', v_code, v_name;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_line_account_guard
BEFORE INSERT ON journal_lines
FOR EACH ROW EXECUTE FUNCTION fn_line_account_guard();

-- ---------------------------------------------------------------------------
-- Integrity trigger 3 — immutability. History is append-only.
-- Fix mistakes with a reversing entry (the app has a one-click Reverse).
-- Entry headers allow editing only description/reference.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_lines_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'Journal lines are immutable. Post a reversing entry instead (entry %)',
        COALESCE(NEW.entry_id, OLD.entry_id);
END $$;

CREATE TRIGGER trg_lines_immutable
BEFORE UPDATE OR DELETE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION fn_lines_immutable();

CREATE OR REPLACE FUNCTION fn_entries_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'Journal entries cannot be deleted. Post a reversing entry instead (entry %)',
            OLD.id;
    END IF;
    IF NEW.scenario_id <> OLD.scenario_id
       OR NEW.entry_date <> OLD.entry_date
       OR NEW.reverses_entry_id IS DISTINCT FROM OLD.reverses_entry_id THEN
        RAISE EXCEPTION
            'Only description and reference of a posted entry may be edited (entry %)',
            OLD.id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_entries_guard
BEFORE UPDATE OR DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION fn_entries_guard();

-- ---------------------------------------------------------------------------
-- Integrity trigger 4 — locked scenarios accept no new entries.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_scenario_lock_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_locked BOOLEAN;
    v_code   TEXT;
BEGIN
    SELECT is_locked, code INTO v_locked, v_code
      FROM scenarios WHERE id = NEW.scenario_id;
    IF v_locked THEN
        RAISE EXCEPTION 'Scenario % is locked; unlock it to post', v_code;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_scenario_lock_guard
BEFORE INSERT ON journal_entries
FOR EACH ROW EXECUTE FUNCTION fn_scenario_lock_guard();

-- ---------------------------------------------------------------------------
-- Reporting layer — the views Power BI / Excel will consume.
-- ---------------------------------------------------------------------------

-- Account dimension with full hierarchy path and normal balance side.
CREATE VIEW v_dim_account AS
WITH RECURSIVE tree AS (
    SELECT id, code, name, account_type, parent_id, is_postable, is_active,
           currency, name::text AS path, 1 AS depth,
           code::text AS sort_path
      FROM accounts
     WHERE parent_id IS NULL
    UNION ALL
    SELECT a.id, a.code, a.name, a.account_type, a.parent_id, a.is_postable,
           a.is_active, a.currency,
           tree.path || ' : ' || a.name,
           tree.depth + 1,
           tree.sort_path || '.' || a.code
      FROM accounts a
      JOIN tree ON a.parent_id = tree.id
)
SELECT id, code, name, account_type, parent_id, is_postable, is_active,
       currency, path, depth, sort_path,
       CASE WHEN account_type IN ('asset', 'expense')
            THEN 'debit' ELSE 'credit' END AS normal_side
  FROM tree;

-- The star-schema fact view: one row per journal line, fully described.
CREATE VIEW v_fact_lines AS
SELECT l.id                                   AS line_id,
       e.id                                   AS entry_id,
       e.entry_date,
       (date_trunc('month', e.entry_date))::date AS month,
       s.id                                   AS scenario_id,
       s.code                                 AS scenario_code,
       s.name                                 AS scenario_name,
       s.scenario_type,
       a.id                                   AS account_id,
       a.code                                 AS account_code,
       a.name                                 AS account_name,
       a.account_type,
       l.amount,
       l.debit,
       l.credit,
       l.memo,
       e.description,
       e.reference,
       e.reverses_entry_id
  FROM journal_lines   l
  JOIN journal_entries e ON e.id = l.entry_id
  JOIN scenarios       s ON s.id = e.scenario_id
  JOIN accounts        a ON a.id = l.account_id;

-- Monthly activity per account per scenario — the budget-vs-actual base.
CREATE VIEW v_monthly_activity AS
SELECT scenario_code, scenario_type, month,
       account_id, account_code, account_name, account_type,
       SUM(amount) AS net,
       SUM(debit)  AS total_debits,
       SUM(credit) AS total_credits,
       COUNT(*)    AS line_count
  FROM v_fact_lines
 GROUP BY scenario_code, scenario_type, month,
          account_id, account_code, account_name, account_type;

-- Date dimension for BI models (2020–2035).
CREATE VIEW v_dim_date AS
SELECT d::date                        AS date,
       EXTRACT(YEAR    FROM d)::int   AS year,
       EXTRACT(QUARTER FROM d)::int   AS quarter,
       EXTRACT(MONTH   FROM d)::int   AS month_num,
       to_char(d, 'YYYY-MM')          AS year_month,
       to_char(d, 'TMMonth')          AS month_name,
       EXTRACT(ISODOW  FROM d)::int   AS iso_weekday,
       (date_trunc('month', d))::date AS month_start
  FROM generate_series('2020-01-01'::date, '2035-12-31'::date, '1 day') AS d;

-- ---------------------------------------------------------------------------
-- Trial balance as a set-returning function (parameterised: scenario, as-of).
-- Includes every active postable account, even with no activity, so the
-- statement reads like a real TB. Debit/credit balance presented per the
-- classic convention: net > 0 sits in the debit column, net < 0 in credit.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_trial_balance(
    p_scenario TEXT DEFAULT 'ACTUAL',
    p_as_of    DATE DEFAULT NULL
)
RETURNS TABLE (
    account_id     BIGINT,
    account_code   TEXT,
    account_name   TEXT,
    acct_type      account_type,
    path           TEXT,
    total_debits   NUMERIC(18,2),
    total_credits  NUMERIC(18,2),
    net            NUMERIC(18,2),
    debit_balance  NUMERIC(18,2),
    credit_balance NUMERIC(18,2)
)
LANGUAGE sql STABLE AS $$
    SELECT da.id,
           da.code,
           da.name,
           da.account_type,
           da.path,
           COALESCE(SUM(f.debit),  0)::numeric(18,2),
           COALESCE(SUM(f.credit), 0)::numeric(18,2),
           COALESCE(SUM(f.amount), 0)::numeric(18,2),
           GREATEST(COALESCE(SUM(f.amount), 0),  0)::numeric(18,2),
           GREATEST(-COALESCE(SUM(f.amount), 0), 0)::numeric(18,2)
      FROM v_dim_account da
      LEFT JOIN v_fact_lines f
             ON f.account_id = da.id
            AND f.scenario_code = p_scenario
            AND f.entry_date <= COALESCE(p_as_of, 'infinity'::date)
     WHERE da.is_postable AND da.is_active
     GROUP BY da.id, da.code, da.name, da.account_type, da.path, da.sort_path
     ORDER BY da.sort_path;
$$;

COMMIT;
