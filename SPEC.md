# Libro — design specification

## The single organizing idea

A general ledger is a set of facts (journal lines) constrained by one
invariant: within an entry, debits equal credits. Everything else —
statements, budgets, variance — is a *query over those facts*. Libro
therefore has exactly one write path (post an entry) and pushes every
invariant into PostgreSQL, so the set of facts can never be inconsistent
regardless of which client wrote them.

## Decisions and rationale

### 1. Signed amounts are canonical; debit/credit are derived

`journal_lines.amount` is signed: debit = positive, credit = negative.
The double-entry invariant becomes `SUM(amount) = 0` per entry — one number
to check, no pair of columns to keep consistent. `debit` and `credit` are
`GENERATED ALWAYS ... STORED` columns, so the familiar two-column
presentation exists everywhere (screens, views, BI) but *cannot* disagree
with the canonical amount. GnuCash's rational `value_num/value_denom` pairs
were rejected as BI-hostile; Actual's integer minor units were rejected
because `NUMERIC(18,2)` gives exact decimal arithmetic that SUMs natively
in SQL, DAX and Excel without a /100 convention.

### 2. The balance invariant lives in a deferred constraint trigger

A plain CHECK cannot see across rows. Application-level checks can be
bypassed by any other client — which is exactly GnuCash's architecture and
the failure mode to avoid. So Libro uses a `CONSTRAINT TRIGGER ... 
DEFERRABLE INITIALLY DEFERRED`: the app inserts header and lines inside one
transaction, and at COMMIT PostgreSQL re-derives `SUM(amount)` for every
touched entry. If it isn't zero (in an enforcing scenario), the commit
fails and the entire entry vanishes atomically. There is no code path
around this — not from the app, not from psql, not from a future importer.

### 3. Scenario is a dimension, not a module (the OneStream model)

`scenarios(code, scenario_type, enforce_balance, is_locked)` and every
entry carries `scenario_id`. ACTUAL, BUD2026, FCST_2026_09 are all just
tags on the same fact table, so budget-vs-actual is a `GROUP BY` with two
`FILTER` clauses — never a reconciliation between modules.

`enforce_balance` resolves the tension between ledger purity and CPM-style
planning:

- **TRUE** — the scenario is a real set of books. A budget built this way
  is a fully articulated *projected* P&L and balance sheet (credit Checking
  when you plan rent — cash forecasting falls out for free).
- **FALSE** — single-sided planning entries allowed: "Groceries 6,000 in
  March," no counter-account, the way you'd type it into a CPM grid.

A CHECK constraint forbids ACTUAL from ever having `enforce_balance =
FALSE`. Locking a scenario (month-end close, board-approved budget) blocks
new entries via trigger.

### 4. History is append-only

Posted lines accept no UPDATE or DELETE (trigger-enforced); entry headers
allow editing only description and reference. Corrections are reversing
entries — `reverses_entry_id` links them, the UI offers one-click Reverse
and refuses to reverse twice. An audit trail you can't rewrite is worth
more than the convenience of editing, and it is how real books work.

### 5. Hierarchy with typed integrity

Accounts form a tree (`parent_id`). Only leaves (`is_postable`) accept
lines, so summary accounts are pure structure. Triggers enforce that a
child's `account_type` matches its parent's and that the tree stays
acyclic. `normal_side` (debit for assets/expenses, credit for
liabilities/equity/income) is derived in `v_dim_account`, never stored —
it is a function of type, so storing it would only create a chance for it
to be wrong.

### 6. The reporting layer is part of the schema

`v_fact_lines` (line-grain fact), `v_dim_account` (recursive path, depth,
normal side), `v_dim_date`, `v_monthly_activity` (account × month ×
scenario) form a star schema Power BI can consume without transformation.
`fn_trial_balance(scenario, as_of)` is a set-returning function — a
parameterized statement, callable from the app, psql, or BI alike. The
philosophy: if a number matters, it should be computable by SQL alone.

### 7. Thin application, no ORM

`db/schema.sql` is the single source of truth; the FastAPI layer is plain
SQL through psycopg3. Every query in the app can be pasted into psql.
Server-rendered Jinja2 + ~100 lines of vanilla JS; no build step, no SPA.
The journal entry screen is keyboard-first — account, debit *or* credit,
Tab, next line appears — with a live balance bar; the Post button unlocks
only when the entry balances (client courtesy; the database re-checks at
commit regardless).

## Extension roadmap

- **Entity dimension** — add `entities` and `entity_id` on entries, and the
  same fact table consolidates multiple sets of books (elimination entries
  become just another scenario or a dedicated elimination entity, exactly
  as in CPM practice).
- **Multi-currency** — accounts already carry `currency`; add a `prices`
  table (GnuCash's one good idea worth importing) and translate in views.
- **Periods & closing** — a fiscal calendar table, closing entries
  generated per period, `is_locked` graduating from scenario-level to
  period-level.
- **Recurring entries** — templates + a scheduler posting real entries.
- **Import** — CSV/CAMT bank import posting suggested entries to a staging
  scenario for review before promotion to ACTUAL.
