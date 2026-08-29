-- ============================================================================
-- POSTWARDEN — a personal general ledger with scenarios
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
--      (the OneStream model). ACTUAL and any full scenario (a forecast or
--      what-if actually modeling dated hypothetical transactions — "what
--      if I buy a house") are journal entries tagged with a scenario,
--      same as always. An income-statement-only scenario (see
--      scenarios.income_statement_only) opts out of the ledger entirely:
--      a monthly expense/income budget isn't a transaction — no date, no
--      counter-account, nothing to balance — so it lives in budget_lines
--      instead, a plain table of amounts a scenario can never post
--      journal entries into.
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
-- schema_version — tracks which db/migrations/NNN_*.sql files an existing
-- database has already applied (app/migrate.py, run once at app startup).
-- Irrelevant to a *fresh* install: this file already represents the current
-- state, so the row below is seeded to the highest migration number that
-- existed when this schema.sql was last regenerated — nothing in
-- db/migrations/ gets replayed on top of a brand-new database. It only
-- matters for an *existing* database catching up after a `git pull`.
-- One row, one column, on purpose — there's exactly one database per
-- instance, never a fleet to track independently.
--
-- Seeded to 0, not a leftover migration number: db/migrations/ is
-- currently empty on purpose (see its own README.md and CLAUDE.md's
-- "Numbered migrations are on the shelf for now") — every schema change
-- right now folds straight into this file instead.
-- ---------------------------------------------------------------------------
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version (version) VALUES (0);

-- ---------------------------------------------------------------------------
-- Users and sessions — application-level authentication.
--
-- Every route in the app requires a valid session (enforced in app/main.py,
-- not here — this table just holds the truth it checks against). Passwords
-- are hashed with bcrypt in the app layer; the hash is the only thing that
-- ever reaches SQL. A session is an opaque random token looked up on every
-- request — no signing secret to manage or rotate, and revoking one (or
-- all of a user's sessions, e.g. on password reset) is just a DELETE.
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE
                  CHECK (username = lower(username) AND username ~ '^[a-z0-9_.-]{3,32}$'),
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    token       TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_sessions_user    ON sessions(user_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- ---------------------------------------------------------------------------
-- Account levels — user-named steps down the chart of accounts (depth 1 =
-- the tree's roots, depth 2 = their children, ...). Purely a labeling
-- layer over the hierarchy accounts.parent_id already builds — the tree
-- itself is still unlimited depth, always was. A scenario can optionally
-- pick one of these as its base_level (below) so it can post to a whole
-- branch (e.g. "Bank") without touching every leaf under it — vertical
-- extensibility, OneStream-style. Defined ahead of scenarios so that
-- table can reference this one.
-- ---------------------------------------------------------------------------
CREATE TABLE account_levels (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    depth      SMALLINT NOT NULL UNIQUE CHECK (depth > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
-- base_level: NULL (the default) changes nothing — entries in this
--   scenario may only post to true leaf accounts, same as always. Set it
--   to let this scenario also post to any account sitting exactly at that
--   level, summary or not — e.g. base_level = "Subaccounts" lets a budget
--   scenario post straight to "Bank" instead of splitting across
--   Checking/Savings. Additive only: it never blocks posting to a real
--   leaf, even one deeper than base_level (fn_line_account_guard). Only
--   meaningful for a full (non-income-statement-only) scenario — an
--   income-statement-only one has no journal entries to relax the target
--   of in the first place.
-- income_statement_only: FALSE (the default) changes nothing — a full
--   scenario, journal entries across the whole chart of accounts, same as
--   ACTUAL. TRUE turns off journal-entry posting for this scenario
--   entirely (fn_income_statement_only_guard below) — it can only carry
--   income/expense amounts in budget_lines, edited from the Budget page's
--   grid instead of the Journal. That's the right shape for "what do I
--   plan to spend on groceries this year," which never had a date or a
--   counter-account to begin with; it's the wrong shape for "what if I
--   buy a house," which does — that stays a full scenario.
-- is_staging: FALSE for every scenario except the one seeded row this
--   whole app treats as "Staging" — a holding pen for entries that
--   shouldn't count as real books yet: materialize_due_schedules()'s
--   copies, or a CSV import (see import_batches). TRUE turns off
--   *manual* entry into this scenario (fn_staging_manual_entry_guard
--   below): a journal_entries row may only land here as the by-product of
--   one of those two automated producers (scheduled_entry_id IS NOT NULL
--   or import_batch_id IS NOT NULL), never typed in from New entry —
--   approving it into its real target scenario is the one way a Staging
--   entry becomes a manual decision. uq_one_staging_scenario below caps
--   this at one row, ever; the app looks it up by this flag instead of by
--   a hardcoded scenario code.
-- ---------------------------------------------------------------------------
CREATE TABLE scenarios (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                   TEXT NOT NULL UNIQUE
                           CHECK (code = upper(code) AND code ~ '^[A-Z0-9_]{2,24}$'),
    name                   TEXT NOT NULL,
    scenario_type          scenario_type NOT NULL,
    enforce_balance        BOOLEAN NOT NULL DEFAULT TRUE,
    income_statement_only  BOOLEAN NOT NULL DEFAULT FALSE,
    is_staging             BOOLEAN NOT NULL DEFAULT FALSE,
    is_locked              BOOLEAN NOT NULL DEFAULT FALSE,
    base_level_id          BIGINT REFERENCES account_levels(id) ON DELETE RESTRICT,
    notes                  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The ACTUAL scenario must always enforce balance: your books are your books.
ALTER TABLE scenarios ADD CONSTRAINT actual_must_balance
    CHECK (NOT (scenario_type = 'actual' AND enforce_balance = FALSE));

-- ...and can't be income-statement-only either — that's a real ledger,
-- every account type, always.
ALTER TABLE scenarios ADD CONSTRAINT actual_not_income_statement_only
    CHECK (NOT (scenario_type = 'actual' AND income_statement_only));

-- A staging scenario is a holding pen for real entries awaiting approval —
-- it can never also be the income-statement-only kind, which has no
-- journal entries (and so nothing to approve) in the first place.
ALTER TABLE scenarios ADD CONSTRAINT staging_not_income_statement_only
    CHECK (NOT (is_staging AND income_statement_only));

-- At most one scenario is ever "the" staging scenario — indexing the
-- column itself, filtered to true rows, means a second TRUE row collides
-- with the first on the same indexed value.
CREATE UNIQUE INDEX uq_one_staging_scenario ON scenarios (is_staging) WHERE is_staging;

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
    -- Marks an account as "cash" for the Cash Flow Statement (see
    -- fn_cash_flow_lines below) — checking/savings/physical cash, not a
    -- credit card, loan, or investment/brokerage account. A per-account
    -- editorial choice, not derived from account_type: several asset
    -- accounts (1310 Brokerage, 1320 Retirement) are deliberately left
    -- FALSE by db/seed.sql because "spendable cash" and "asset" aren't
    -- the same boundary. Default FALSE so an existing install's chart
    -- shows nothing on the Cash Flow Statement until accounts are
    -- explicitly opted in from /accounts, rather than silently guessing.
    is_cashflow  BOOLEAN NOT NULL DEFAULT FALSE,
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
-- Payees — who the money went to or came from. One per entry (unlike tags,
-- which are many-to-many), so it's a plain FK on journal_entries rather
-- than a junction table.
-- ---------------------------------------------------------------------------
CREATE TABLE payees (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE CHECK (name = trim(name) AND length(name) BETWEEN 1 AND 80),
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Scheduled entries — a template plus a recurrence rule. materialize_due_
-- schedules() (app/main.py, run lazily on request rather than a real cron —
-- there's no task runner in this deployment) posts a copy into the Staging
-- scenario once next_date arrives; a human still has to approve it from
-- there before it's real (see journal_entries.scheduled_entry_id /
-- promoted_entry_id below). Defined ahead of journal_entries so that table
-- can reference this one.
-- ---------------------------------------------------------------------------
CREATE TABLE scheduled_entries (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    description         TEXT NOT NULL CHECK (length(trim(description)) > 0),
    reference           TEXT,
    payee_id            BIGINT REFERENCES payees(id) ON DELETE SET NULL,
    -- Where an occurrence lands once approved — Staging is just a layover.
    target_scenario_id  BIGINT NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
    interval_unit       TEXT NOT NULL CHECK (interval_unit IN ('day', 'week', 'month')),
    interval_count      SMALLINT NOT NULL DEFAULT 1 CHECK (interval_count > 0),
    next_date           DATE NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_scheduled_entries_due
    ON scheduled_entries(next_date) WHERE is_active;

CREATE TABLE scheduled_entry_lines (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scheduled_entry_id  BIGINT NOT NULL REFERENCES scheduled_entries(id) ON DELETE CASCADE,
    line_no             SMALLINT NOT NULL CHECK (line_no > 0),
    account_id          BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount              NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    debit               NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
                        (CASE WHEN amount > 0 THEN amount ELSE 0 END) STORED,
    credit              NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
                        (CASE WHEN amount < 0 THEN -amount ELSE 0 END) STORED,
    memo                TEXT,
    UNIQUE (scheduled_entry_id, line_no)
);

CREATE INDEX idx_scheduled_entry_lines_parent ON scheduled_entry_lines(scheduled_entry_id);

-- ---------------------------------------------------------------------------
-- Import batches — one row per CSV import (app/main.py's /import), the
-- second producer Staging accepts entries from (see
-- fn_staging_manual_entry_guard). A single upload targets exactly one
-- scenario, chosen on the import form itself rather than trusted from a
-- column inside the uploaded file — every journal_entries row the import
-- creates carries this batch's id (journal_entries.import_batch_id) the
-- same way a materialized schedule occurrence carries scheduled_entry_id.
-- row_count is how many entries actually landed in Staging, which can be
-- less than the CSV's own row count if some groups failed validation
-- (an unbalanced group, an unknown account code, ...) — those are
-- reported back to the importer and never touch the database at all.
-- ---------------------------------------------------------------------------
CREATE TABLE import_batches (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename            TEXT NOT NULL,
    target_scenario_id  BIGINT NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
    imported_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    row_count           SMALLINT NOT NULL CHECK (row_count > 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Entry templates — reusable scaffolding for New entry ("Load template"),
-- not a posting on their own and not linked to any journal_entries row.
-- Same shape as scheduled_entries minus the recurrence columns.
-- ---------------------------------------------------------------------------
CREATE TABLE entry_templates (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE CHECK (name = trim(name) AND length(name) BETWEEN 1 AND 80),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    reference   TEXT,
    payee_id    BIGINT REFERENCES payees(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE entry_template_lines (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    template_id BIGINT NOT NULL REFERENCES entry_templates(id) ON DELETE CASCADE,
    line_no     SMALLINT NOT NULL CHECK (line_no > 0),
    account_id  BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount      NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    debit       NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
                (CASE WHEN amount > 0 THEN amount ELSE 0 END) STORED,
    credit      NUMERIC(18,2) NOT NULL GENERATED ALWAYS AS
                (CASE WHEN amount < 0 THEN -amount ELSE 0 END) STORED,
    memo        TEXT,
    UNIQUE (template_id, line_no)
);

CREATE INDEX idx_entry_template_lines_parent ON entry_template_lines(template_id);

-- ---------------------------------------------------------------------------
-- Journal entries (header) and journal lines (the fact table)
-- ---------------------------------------------------------------------------
-- journal_entries.id is a random 6-character code (A-Z0-9), not a
-- sequential integer — see SPEC.md's entry-id decision for why. Defined
-- ahead of the table so it can be the column's DEFAULT; the collision
-- check queries journal_entries itself, which is fine even while this
-- function is only ever called *for* an INSERT into that same table —
-- by the time a row is actually being inserted, the table already
-- exists and already holds whatever rows came before it.
CREATE OR REPLACE FUNCTION fn_generate_entry_id() RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    -- No ambiguous-character exclusion (0/O, 1/I/L, ...) — the full 36-
    -- symbol alphabet keeps the collision math simple, and this app
    -- doesn't ask anyone to read one aloud or copy it by hand often
    -- enough for that ambiguity to matter in practice.
    v_alphabet CONSTANT TEXT := 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    v_id       TEXT;
BEGIN
    LOOP
        SELECT string_agg(substr(v_alphabet, (floor(random() * 36) + 1)::int, 1), '')
          INTO v_id
          FROM generate_series(1, 6);
        EXIT WHEN NOT EXISTS (SELECT 1 FROM journal_entries WHERE id = v_id);
    END LOOP;
    RETURN v_id;
END $$;

CREATE TABLE journal_entries (
    id                 TEXT PRIMARY KEY DEFAULT fn_generate_entry_id()
                       CHECK (id ~ '^[A-Z0-9]{6}$'),
    scenario_id        BIGINT NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
    entry_date         DATE NOT NULL,
    description        TEXT NOT NULL CHECK (length(trim(description)) > 0),
    reference          TEXT,
    reverses_entry_id  TEXT REFERENCES journal_entries(id) ON DELETE RESTRICT,
    payee_id           BIGINT REFERENCES payees(id) ON DELETE SET NULL,
    -- Set when this entry was auto-posted to the Staging scenario by a
    -- schedule (see scheduled_entries below) — lets the admin page find
    -- "everything from this schedule" and the app skip re-materializing
    -- the same occurrence twice.
    scheduled_entry_id BIGINT REFERENCES scheduled_entries(id) ON DELETE SET NULL,
    -- The other producer allowed to write to Staging — set when this
    -- entry came from a CSV import (see import_batches above) rather than
    -- a schedule. An entry never has both set.
    import_batch_id    BIGINT REFERENCES import_batches(id) ON DELETE SET NULL,
    -- Set on a Staging entry once approved: the id of the real entry it
    -- was copied into. NULL means "still awaiting approval" for anything
    -- sitting in Staging.
    promoted_entry_id  TEXT REFERENCES journal_entries(id) ON DELETE SET NULL,
    -- Who posted it, for the audit trail — nullable so direct psql/import
    -- inserts don't need a user, but the app always sets it from the session.
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Purely internal — never displayed, never referenced by the app
    -- except in an ORDER BY. Now that id is a random 6-character code
    -- rather than a sequential integer, something has to stand in for
    -- "which of two same-day entries was posted first" — created_at
    -- itself can't: it defaults to now(), which Postgres fixes once per
    -- *transaction*, not per statement, so a batch of entries inserted
    -- together (a schedule materializing several occurrences at once,
    -- an import, even just this file's own test fixtures) can all land
    -- with the exact same timestamp. A plain identity column sidesteps
    -- that the same way the old id used to, just without being the
    -- thing anyone actually sees or references.
    seq                BIGINT GENERATED ALWAYS AS IDENTITY,
    CHECK (reverses_entry_id <> id),
    CHECK (promoted_entry_id <> id)
);

CREATE INDEX idx_entries_payee ON journal_entries(payee_id) WHERE payee_id IS NOT NULL;

CREATE INDEX idx_entries_scenario_date ON journal_entries(scenario_id, entry_date);

CREATE INDEX idx_entries_scheduled ON journal_entries(scheduled_entry_id)
    WHERE scheduled_entry_id IS NOT NULL;

-- Everything sitting in Staging (any scenario, in practice) still awaiting
-- approval — the admin page's "pending" list is exactly this.
CREATE INDEX idx_entries_pending_promotion ON journal_entries(scheduled_entry_id)
    WHERE scheduled_entry_id IS NOT NULL AND promoted_entry_id IS NULL;

-- An entry may be reversed at most once. This is also the invariant the app
-- relies on to show "reversed by #N" and to refuse a second Reverse click —
-- enforcing it here (not just in app.py) closes the race where two
-- concurrent reversal requests could otherwise both succeed.
CREATE UNIQUE INDEX uq_one_reversal_per_entry
    ON journal_entries (reverses_entry_id) WHERE reverses_entry_id IS NOT NULL;

CREATE TABLE journal_lines (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id   TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
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
-- Tags — free-form organization across entries, orthogonal to the
-- account/scenario dimensions. Deliberately not covered by the
-- immutability trigger below: they're metadata about an entry, not part
-- of the accounting fact itself, so re-tagging a posted entry is fine.
-- ---------------------------------------------------------------------------
CREATE TABLE tags (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE
               CHECK (name = lower(trim(name)) AND name ~ '^[a-z0-9][a-z0-9 _-]{0,39}$'),
    -- Same shape/meaning as payees.is_active: hides a tag from the tag-
    -- input's suggestion list (all_tags() — see app/main.py) so an old,
    -- unused tag stops cluttering autocomplete, without touching any
    -- entry that already carries it. Never checked by anything that
    -- reads an entry's own tags (tags_by_entry, the per-entry badges) —
    -- only by what offers a tag as something new to pick.
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE journal_entry_tags (
    entry_id TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    tag_id   BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, tag_id)
);

CREATE INDEX idx_journal_entry_tags_tag ON journal_entry_tags(tag_id);

CREATE TABLE scheduled_entry_tags (
    scheduled_entry_id BIGINT NOT NULL REFERENCES scheduled_entries(id) ON DELETE CASCADE,
    tag_id             BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (scheduled_entry_id, tag_id)
);

CREATE TABLE entry_template_tags (
    template_id BIGINT NOT NULL REFERENCES entry_templates(id) ON DELETE CASCADE,
    tag_id      BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (template_id, tag_id)
);

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
    v_entry_id   TEXT;
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
--
-- "Postable" is scenario-relative: always true leaves (accounts.is_postable),
-- plus — if the entry's scenario has a base_level set — any account sitting
-- exactly at that level too, summary or not (see scenarios.base_level_id
-- above). Additive only: a scenario's base_level can never make a true
-- leaf un-postable, only add coarser accounts as options.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_line_account_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_postable   BOOLEAN;
    v_active     BOOLEAN;
    v_code       TEXT;
    v_name       TEXT;
    v_depth      SMALLINT;
    v_walk       BIGINT;
    v_base_level SMALLINT;
BEGIN
    SELECT is_postable, is_active, code, name, parent_id
      INTO v_postable, v_active, v_code, v_name, v_walk
      FROM accounts WHERE id = NEW.account_id;

    IF NOT v_postable THEN
        -- Walk parent_id to this account's depth (root = 1) — self-
        -- contained rather than joining v_dim_account's recursive CTE
        -- from inside a trigger; cheap since accounts.parent_id is
        -- guaranteed acyclic by fn_account_hierarchy_guard.
        v_depth := 1;
        WHILE v_walk IS NOT NULL LOOP
            v_depth := v_depth + 1;
            SELECT parent_id INTO v_walk FROM accounts WHERE id = v_walk;
        END LOOP;

        SELECT al.depth INTO v_base_level
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id
          JOIN account_levels al ON al.id = s.base_level_id
         WHERE e.id = NEW.entry_id;

        IF v_base_level IS DISTINCT FROM v_depth THEN
            RAISE EXCEPTION
                'Account % — % is a summary account; post to a leaf account instead (or a scenario whose base level includes it)',
                v_code, v_name;
        END IF;
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
-- Integrity trigger 3 — immutability, with two deliberate exceptions.
--
-- History is append-only: fix a posted mistake with a reversing entry (the
-- app has a one-click Reverse), never by editing it. Posted entry headers
-- allow editing only description/reference.
--
-- The first exception: an entry still sitting in Staging, awaiting approval
-- (scenarios.is_staging, journal_entries.promoted_entry_id IS NULL) isn't
-- history yet — it's a draft a schedule or an import proposed, nobody has
-- approved it into real books, and "you can't rewrite it" doesn't actually
-- protect anything for a row nothing has relied on yet (see SPEC.md
-- decision 15). So:
--   - A still-pending Staging line may be DELETEd (never UPDATEd in place —
--     "editing" a line is delete-then-reinsert via the app's Staging edit
--     screen, one rule instead of a matrix of which columns are safe to
--     change).
--   - A still-pending Staging entry may itself be DELETEd (Staging's
--     "reject" action — gone for good, not a reversal, since it never was
--     a real posting to reverse), and its date/description/reference/payee
--     may be UPDATEd — never its scenario, provenance
--     (scheduled_entry_id/import_batch_id), reverses_entry_id, or
--     promoted_entry_id.
-- The instant an entry is approved (promoted_entry_id gets set), both
-- exceptions vanish — it's real history from that point on, exactly like
-- anything posted directly.
--
-- The second exception, added later and orthogonal to Staging status
-- entirely: a line's own memo may always be UPDATEd, posted or pending
-- alike, same reasoning decision 16 already gave tags — a memo is
-- organizational metadata about a leg ("annual, not monthly" scribbled
-- next to a subscription charge), not a fact about the transaction the
-- append-only rule exists to protect. Scoped tightly at the trigger
-- level, not just in the app: the UPDATE must leave entry_id, line_no,
-- account_id, and amount all unchanged — anything touching the actual
-- accounting fact still goes through the ordinary "immutable" path below,
-- regardless of which client sends the UPDATE.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_lines_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_deletable BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT s.is_staging AND e.promoted_entry_id IS NULL INTO v_deletable
          FROM journal_entries e JOIN scenarios s ON s.id = e.scenario_id
         WHERE e.id = OLD.entry_id;
        IF v_deletable THEN
            RETURN OLD;
        END IF;
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.entry_id = OLD.entry_id AND NEW.line_no = OLD.line_no
       AND NEW.account_id = OLD.account_id AND NEW.amount = OLD.amount THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'Journal lines are immutable. Post a reversing entry instead (entry %)',
        COALESCE(NEW.entry_id, OLD.entry_id);
END $$;

CREATE TRIGGER trg_lines_immutable
BEFORE UPDATE OR DELETE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION fn_lines_immutable();

CREATE OR REPLACE FUNCTION fn_entries_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_pending BOOLEAN;  -- still in Staging, not yet approved
BEGIN
    SELECT s.is_staging AND OLD.promoted_entry_id IS NULL INTO v_pending
      FROM scenarios s WHERE s.id = OLD.scenario_id;

    IF TG_OP = 'DELETE' THEN
        IF v_pending THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION
            'Journal entries cannot be deleted. Post a reversing entry instead (entry %)',
            OLD.id;
    END IF;

    IF v_pending THEN
        -- promoted_entry_id is deliberately not in this list: v_pending
        -- being true already means OLD.promoted_entry_id IS NULL, so the
        -- only way NEW can differ here is the approve action setting it
        -- for the first time (Staging's own "Approve entries" — see
        -- app/main.py) — the transition this whole exception exists to
        -- still allow, not one more thing to block.
        IF NEW.scenario_id <> OLD.scenario_id
           OR NEW.reverses_entry_id IS DISTINCT FROM OLD.reverses_entry_id
           OR NEW.scheduled_entry_id IS DISTINCT FROM OLD.scheduled_entry_id
           OR NEW.import_batch_id IS DISTINCT FROM OLD.import_batch_id THEN
            RAISE EXCEPTION
                'Cannot change scenario or provenance of a staged entry (entry %)',
                OLD.id;
        END IF;
        RETURN NEW;
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
-- Integrity trigger 5 — an income-statement-only scenario never gets a
-- journal entry, full stop. Belt-and-suspenders alongside the app only
-- ever offering such a scenario through the Budget grid, not the Journal:
-- this is what actually makes it true regardless of what posts the INSERT.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_income_statement_only_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_only BOOLEAN;
    v_code TEXT;
BEGIN
    SELECT income_statement_only, code INTO v_only, v_code
      FROM scenarios WHERE id = NEW.scenario_id;
    IF v_only THEN
        RAISE EXCEPTION
            'Scenario % is income-statement-only — use the Budget page instead of a journal entry',
            v_code;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_income_statement_only_guard
BEFORE INSERT ON journal_entries
FOR EACH ROW EXECUTE FUNCTION fn_income_statement_only_guard();

-- ---------------------------------------------------------------------------
-- Integrity trigger 6 — a staging scenario only ever receives an entry as
-- the by-product of an automated producer, never a manually-typed one.
-- Today that means scheduled_entry_id IS NOT NULL (materialize_due_
-- schedules()'s copies); a future CSV importer gets its own exemption
-- added here the same way when it lands, rather than this trigger being
-- loosened to "anything goes."
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_staging_manual_entry_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_staging BOOLEAN;
    v_code    TEXT;
BEGIN
    SELECT is_staging, code INTO v_staging, v_code
      FROM scenarios WHERE id = NEW.scenario_id;
    IF v_staging AND NEW.scheduled_entry_id IS NULL AND NEW.import_batch_id IS NULL THEN
        RAISE EXCEPTION
            'Scenario % only accepts entries from a schedule or an import, never a manual posting',
            v_code;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_staging_manual_entry_guard
BEFORE INSERT ON journal_entries
FOR EACH ROW EXECUTE FUNCTION fn_staging_manual_entry_guard();

-- ---------------------------------------------------------------------------
-- Budget lines — the income-statement-only counterpart to journal_entries.
-- One row per (scenario, account, month): a plain amount, not a
-- transaction — no date beyond the month, no counter-account, nothing to
-- balance. A cell in the Budget grid is a straight UPSERT here, and can be
-- edited freely (unlike journal_lines, there's no audit-trail reason for
-- append-only history over a working assumption).
-- ---------------------------------------------------------------------------
CREATE TABLE budget_lines (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_id  BIGINT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    account_id   BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    period_month DATE NOT NULL CHECK (EXTRACT(DAY FROM period_month) = 1),
    amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_id, account_id, period_month)
);

-- Integrity trigger 6 — a budget line only ever belongs to an
-- income-statement-only scenario, only ever targets a postable income or
-- expense account, and never lands in a locked scenario. Mirrors
-- fn_line_account_guard/fn_scenario_lock_guard's job, just for this table.
CREATE OR REPLACE FUNCTION fn_budget_line_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_only     BOOLEAN;
    v_locked   BOOLEAN;
    v_code     TEXT;
    v_type     account_type;
    v_postable BOOLEAN;
    v_active   BOOLEAN;
    v_acct     TEXT;
    v_name     TEXT;
BEGIN
    SELECT income_statement_only, is_locked, code
      INTO v_only, v_locked, v_code
      FROM scenarios WHERE id = NEW.scenario_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown scenario %', NEW.scenario_id;
    END IF;
    IF NOT v_only THEN
        RAISE EXCEPTION
            'Scenario % is not income-statement-only — budget lines aren''t allowed here',
            v_code;
    END IF;
    IF v_locked THEN
        RAISE EXCEPTION 'Scenario % is locked; unlock it to edit the budget', v_code;
    END IF;

    SELECT account_type, is_postable, is_active, code, name
      INTO v_type, v_postable, v_active, v_acct, v_name
      FROM accounts WHERE id = NEW.account_id;
    IF v_type NOT IN ('income', 'expense') THEN
        RAISE EXCEPTION
            'Account % — % is not an income or expense account', v_acct, v_name;
    END IF;
    IF NOT v_postable THEN
        RAISE EXCEPTION
            'Account % — % is a summary account; budget a leaf account instead',
            v_acct, v_name;
    END IF;
    IF NOT v_active THEN
        RAISE EXCEPTION 'Account % — % is inactive', v_acct, v_name;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER trg_budget_line_guard
BEFORE INSERT OR UPDATE ON budget_lines
FOR EACH ROW EXECUTE FUNCTION fn_budget_line_guard();

-- ---------------------------------------------------------------------------
-- Reporting layer — the views Power BI / Excel will consume.
-- ---------------------------------------------------------------------------

-- Account dimension with full hierarchy path and normal balance side.
-- `path` is the full breadcrumb including the account's own name (e.g.
-- "Fixed & Essential Living (Needs) : Housing & Utilities : Rent /
-- Mortgage Interest") — the right thing for a picker/dropdown where no
-- other column names the account. `parent_path` is the same breadcrumb
-- with the account's own name dropped off the end (NULL at the root) —
-- the right thing anywhere the account's name is *also* shown next to
-- it (every report row), so the name doesn't get echoed back a second
-- time inside its own path.
CREATE VIEW v_dim_account AS
WITH RECURSIVE tree AS (
    SELECT id, code, name, account_type, parent_id, is_postable, is_active,
           is_cashflow, name::text AS path, NULL::text AS parent_path,
           1 AS depth, code::text AS sort_path
      FROM accounts
     WHERE parent_id IS NULL
    UNION ALL
    SELECT a.id, a.code, a.name, a.account_type, a.parent_id, a.is_postable,
           a.is_active, a.is_cashflow,
           tree.path || ' : ' || a.name,
           tree.path,
           tree.depth + 1,
           tree.sort_path || '.' || a.code
      FROM accounts a
      JOIN tree ON a.parent_id = tree.id
)
SELECT id, code, name, account_type, parent_id, is_postable, is_active,
       is_cashflow, path, parent_path, depth, sort_path,
       CASE WHEN account_type IN ('asset', 'expense')
            THEN 'debit' ELSE 'credit' END AS normal_side
  FROM tree;

-- The star-schema fact view: one row per journal line, fully described.
CREATE VIEW v_fact_lines AS
SELECT l.id                                   AS line_id,
       e.id                                   AS entry_id,
       e.entry_date,
       -- Entry ids are a random 6-character code (see SPEC.md), not a
       -- sequential integer, so they can't stand in for "which entry
       -- was posted more recently" the way an ORDER BY entry_id DESC
       -- tiebreaker used to. Exposed here so /api/entries can use it
       -- instead — the one v_fact_lines consumer outside this app that
       -- needs a stable "most recent first" ordering. created_at isn't
       -- enough on its own for that — Postgres fixes now() once per
       -- transaction, so a batch of entries inserted together can share
       -- one timestamp — seq (a plain identity column, never otherwise
       -- referenced) is the one that's actually always distinct.
       e.created_at, e.seq,
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
       e.reverses_entry_id,
       u.username                             AS posted_by,
       p.name                                 AS payee,
       COALESCE(t.tag_names, ARRAY[]::text[]) AS tags
  FROM journal_lines   l
  JOIN journal_entries e ON e.id = l.entry_id
  JOIN scenarios       s ON s.id = e.scenario_id
  JOIN accounts        a ON a.id = l.account_id
  LEFT JOIN users       u ON u.id = e.created_by_user_id
  LEFT JOIN payees      p ON p.id = e.payee_id
  LEFT JOIN (
      SELECT jet.entry_id, array_agg(tg.name ORDER BY tg.name) AS tag_names
        FROM journal_entry_tags jet
        JOIN tags tg ON tg.id = jet.tag_id
       GROUP BY jet.entry_id
  ) t ON t.entry_id = e.id;

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
-- Trial balance as a set-returning function (parameterised: scenario, as-of,
-- and an optional period start). Includes every active postable account,
-- even with no activity, so the statement reads like a real TB. Debit/
-- credit balance presented per the classic convention: net > 0 sits in the
-- debit column, net < 0 in credit.
--
-- p_from is optional and defaults to NULL (the beginning of time) — every
-- existing 2-argument call site (Trial Balance, Balance Sheet: both
-- inherently cumulative-since-inception "as of" reports) is unaffected.
-- Passing p_from turns this into a *period* balance instead of a running
-- one — that's what the Income Statement uses it for, since Income/Expense
-- are flow accounts (measured over a range) rather than stock accounts
-- (measured as of a point in time). Deliberately the same function rather
-- than a second one: one balance-computation query, two ways to bound it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_trial_balance(
    p_scenario TEXT DEFAULT 'ACTUAL',
    p_as_of    DATE DEFAULT NULL,
    p_from     DATE DEFAULT NULL
)
RETURNS TABLE (
    account_id     BIGINT,
    account_code   TEXT,
    account_name   TEXT,
    acct_type      account_type,
    path           TEXT,
    sort_path      TEXT,
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
           da.sort_path,
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
            AND f.entry_date >= COALESCE(p_from, '-infinity'::date)
     WHERE da.is_active
       -- True leaves always show, same as always. A summary account only
       -- shows if it actually has postings in *this* scenario (within the
       -- same window) — that's how a scenario's base_level
       -- (fn_line_account_guard) lets one post straight to e.g. "Bank"
       -- without every leaf under it; if this stayed is_postable-only,
       -- that money would silently vanish from Trial Balance despite
       -- genuinely being posted. Each account still shows its own direct
       -- postings only — no rollup summing a summary account's
       -- descendants into it.
       AND (da.is_postable OR EXISTS (
           SELECT 1 FROM v_fact_lines f2
            WHERE f2.account_id = da.id AND f2.scenario_code = p_scenario
              AND f2.entry_date <= COALESCE(p_as_of, 'infinity'::date)
              AND f2.entry_date >= COALESCE(p_from, '-infinity'::date)))
     GROUP BY da.id, da.code, da.name, da.account_type, da.path, da.sort_path
     ORDER BY da.sort_path;
$$;

-- ---------------------------------------------------------------------------
-- Every active account's own direct balance — leaf or summary, posted-to
-- or not, no filtering at all. Unlike fn_trial_balance (which hides a
-- summary account with nothing posted straight to it), this is the base
-- Trial Balance/Balance Sheet build a hierarchical tree from: a summary
-- account needs a row here even at $0 of its own, since its displayed
-- total is computed by rolling its children up onto it in application
-- code, not by this function.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_account_balances(
    p_scenario TEXT DEFAULT 'ACTUAL',
    p_as_of    DATE DEFAULT NULL,
    p_from     DATE DEFAULT NULL
)
RETURNS TABLE (
    account_id BIGINT,
    net        NUMERIC(18,2)
)
LANGUAGE sql STABLE AS $$
    SELECT da.id,
           COALESCE(SUM(f.amount), 0)::numeric(18,2)
      FROM v_dim_account da
      LEFT JOIN v_fact_lines f
             ON f.account_id = da.id
            AND f.scenario_code = p_scenario
            AND f.entry_date <= COALESCE(p_as_of, 'infinity'::date)
            AND f.entry_date >= COALESCE(p_from, '-infinity'::date)
     WHERE da.is_active
     GROUP BY da.id;
$$;

-- ---------------------------------------------------------------------------
-- Cash Flow Statement — the finest-grained artifact one row per
-- (transaction, contra account), everything else (the statement itself,
-- the flagged-for-review list, the three-way tie-out) is built on top of
-- this by app/main.py's _cash_flow_rows(). Kept as one function rather
-- than three, per decision 6 ("if a number matters, it should be
-- computable by SQL alone") — every caller (the report, the flagged
-- list, the tie-out) needs the same per-entry attribution, just grouped
-- differently, so there's one source of truth for it instead of three
-- copies of the same CTEs.
--
-- Steps, matching the feature's own spec (SPEC.md decision 20):
--   1. scoped_lines — every line on a transaction that has at least one
--      is_cashflow leg, within [p_from, p_to] (both inclusive, same
--      convention every other report in this app uses).
--   2. entry_shape  — per transaction, how many cash vs. non-cash legs
--      it has, and how many non-cash legs (n_noncash = 0 marks a pure
--      cash-to-cash transfer — checking -> savings, or a 3+-leg split
--      across only cash accounts — excluded here outright; the
--      predicate is "every leg is cash-tagged", not "legs pairwise net
--      to zero", so it still catches a 3+-leg all-cash entry a naive
--      pairwise check would miss).
--   3. The final SELECT attributes each surviving non-cash leg its own
--      amount, sign-flipped — no proportional redistribution by
--      magnitude, and deliberately so. A balanced entry means
--      SUM(all legs) = 0, so SUM(cash legs) = -SUM(non-cash legs)
--      always, for every leg-count shape (1 cash/1 non-cash, 1 cash/N
--      non-cash, N cash/N non-cash alike) — each non-cash leg's own
--      posted amount *is* its exact, already-two-decimal contribution
--      to the cash change; there is nothing to estimate or round. An
--      earlier version of this function instead weighted each leg by
--      its share of total non-cash magnitude (cash_net * abs(amount) /
--      total_noncash_abs) plus a largest-remainder rounding pass to
--      force the shares back to summing exactly — which happens to
--      equal -amount whenever every non-cash leg on the entry shares
--      one sign (the common "split one purchase two ways" case the
--      original feature request was written around), but silently
--      breaks on a transaction whose non-cash legs don't all share a
--      sign: gross-to-net payroll (Dr Cash, Dr Tax Expense × N, Cr
--      Salary Income) proportionally bled part of the salary inflow
--      onto the tax legs, showing withheld tax as if it were separate
--      cash that had arrived. Caught in review against real seed data,
--      not by the largest-remainder property itself, which was busy
--      solving a rounding problem that only existed because of the
--      proportional formula it was patching — see SPEC.md decision 20.
--
-- n_cash_legs is returned per row (not collapsed into a boolean here)
-- so a caller can decide what ">1" means for its own purposes — today
-- that's "flag this transaction for manual review", per the spec's
-- explicit ask, even though the attribution above needs no guessing
-- for that shape either: it's exact by the same balanced-entry identity
-- regardless of how many cash legs a transaction has.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_cash_flow_lines(
    p_scenario TEXT DEFAULT 'ACTUAL',
    p_from     DATE DEFAULT NULL,
    p_to       DATE DEFAULT NULL
)
RETURNS TABLE (
    entry_id           TEXT,
    contra_account_id  BIGINT,
    amount             NUMERIC(18,2),
    n_cash_legs        INT
)
LANGUAGE sql STABLE AS $$
    WITH scoped_lines AS (
        SELECT f.entry_id, f.account_id, f.amount, a.is_cashflow
          FROM v_fact_lines f
          JOIN accounts a ON a.id = f.account_id
         WHERE f.scenario_code = p_scenario
           AND f.entry_date <= COALESCE(p_to, 'infinity'::date)
           AND f.entry_date >= COALESCE(p_from, '-infinity'::date)
           AND f.entry_id IN (
               SELECT f2.entry_id
                 FROM v_fact_lines f2
                 JOIN accounts a2 ON a2.id = f2.account_id
                WHERE a2.is_cashflow
                  AND f2.scenario_code = p_scenario
                  AND f2.entry_date <= COALESCE(p_to, 'infinity'::date)
                  AND f2.entry_date >= COALESCE(p_from, '-infinity'::date)
           )
    ),
    entry_shape AS (
        SELECT entry_id,
               COUNT(*) FILTER (WHERE is_cashflow)     AS n_cash,
               COUNT(*) FILTER (WHERE NOT is_cashflow) AS n_noncash
          FROM scoped_lines
         GROUP BY entry_id
    )
    SELECT sl.entry_id, sl.account_id, (-sl.amount)::numeric(18,2), es.n_cash
      FROM scoped_lines sl
      JOIN entry_shape es ON es.entry_id = sl.entry_id
     WHERE NOT sl.is_cashflow AND es.n_noncash > 0;
$$;

-- ---------------------------------------------------------------------------
-- Rolled-up balance per account at a chosen depth — the budget-vs-actual
-- base. Unlike fn_trial_balance (native depth, own postings only), this
-- collapses every posting under a common ancestor at p_depth: a leaf's
-- amount rolls up into whichever account sits at p_depth on its own path
-- to the root, so a Budget scenario posted straight to "Bank" (depth 2)
-- lines up against Actual's Checking + Savings postings (depth 3) summed
-- together under that same "Bank" row. A posting shallower than p_depth
-- (nothing to push deeper) stays at its own account — p_depth is a
-- ceiling, not a hard requirement. p_depth NULL means no rollup at all,
-- each account at its own native depth (matches fn_trial_balance's rows,
-- just without the always-show-every-postable-leaf zero rows).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_rollup_balance(
    p_scenario TEXT,
    p_depth    SMALLINT DEFAULT NULL,
    p_as_of    DATE DEFAULT NULL
)
RETURNS TABLE (
    account_id     BIGINT,
    account_code   TEXT,
    account_name   TEXT,
    acct_type      account_type,
    path           TEXT,  -- v_dim_account.parent_path (own name excluded — see its comment); Variance is the one caller and always shows this beside account_name
    sort_path      TEXT,
    total_debits   NUMERIC(18,2),
    total_credits  NUMERIC(18,2),
    net            NUMERIC(18,2),
    debit_balance  NUMERIC(18,2),
    credit_balance NUMERIC(18,2)
)
LANGUAGE sql STABLE AS $$
    WITH targets AS (
        SELECT f.debit, f.credit, f.amount,
               array_to_string(
                   (string_to_array(da.sort_path, '.'))
                       [1:LEAST(da.depth, COALESCE(p_depth, da.depth))],
                   '.'
               ) AS target_sort_path
          FROM v_fact_lines f
          JOIN v_dim_account da ON da.id = f.account_id
         WHERE f.scenario_code = p_scenario
           AND f.entry_date <= COALESCE(p_as_of, 'infinity'::date)
    )
    SELECT da.id, da.code, da.name, da.account_type, da.parent_path, da.sort_path,
           COALESCE(SUM(t.debit),  0)::numeric(18,2),
           COALESCE(SUM(t.credit), 0)::numeric(18,2),
           COALESCE(SUM(t.amount), 0)::numeric(18,2),
           GREATEST(COALESCE(SUM(t.amount), 0),  0)::numeric(18,2),
           GREATEST(-COALESCE(SUM(t.amount), 0), 0)::numeric(18,2)
      FROM targets t
      JOIN v_dim_account da ON da.sort_path = t.target_sort_path
     GROUP BY da.id, da.code, da.name, da.account_type, da.parent_path, da.sort_path
     ORDER BY da.sort_path;
$$;

-- ---------------------------------------------------------------------------
-- Read-only role for BI tools (Power BI, Excel, psql) connecting straight to
-- the database instead of through the app — SPEC.md decision 14.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'postwarden_bi') THEN
        CREATE ROLE postwarden_bi LOGIN PASSWORD 'postwarden_bi';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE postwarden TO postwarden_bi;
GRANT USAGE ON SCHEMA public TO postwarden_bi;
GRANT SELECT ON v_dim_account, v_fact_lines, v_dim_date, v_monthly_activity TO postwarden_bi;
GRANT EXECUTE ON FUNCTION fn_trial_balance(TEXT, DATE, DATE) TO postwarden_bi;
GRANT EXECUTE ON FUNCTION fn_cash_flow_lines(TEXT, DATE, DATE) TO postwarden_bi;

COMMIT;
