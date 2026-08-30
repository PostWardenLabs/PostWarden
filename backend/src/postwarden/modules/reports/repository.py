"""Raw SQL access for the reports module — every report ultimately reads
through one of the four Postgres set-returning functions REBUILD.md §6
names (`fn_trial_balance`, `fn_account_balances`, `fn_cash_flow_lines`,
`fn_rollup_balance`) plus a handful of plain table/view reads
(`v_dim_account`, `v_fact_lines`, `scenarios`, `account_levels`,
`budget_lines`, `accounts`, `journal_entries`).

Deliberately **not** modeled through SQLAlchemy Core `Table`/`select()`
constructs — REBUILD.md §6's own decision: "Core is for CRUD," and an
enum-typed, generated-column, set-returning-function-backed schema like
this one models awkwardly through Core with nothing gained over a plain
`text()` call. Every function here still goes through the same
SQLAlchemy `Connection` `db.get_connection()` hands every route (so
transactions, pooling, and `pool_pre_ping` are all shared with the rest
of the app) — "not modeled through Core" means no `Table` objects, not
"bypass SQLAlchemy entirely."

Every function takes `conn` as its first argument and returns plain
dicts/lists/scalars — `Decimal` for every money value (`NUMERIC(18,2)`
columns; psycopg's default, unchanged here), never `float`. Nothing in
this file makes a decision beyond "here is the row Postgres returned" —
that's `service.py`'s job.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection


def dim_accounts(conn: Connection, *, income_expense_only: bool = False) -> list[dict]:
    """Every active account, ordered so a parent always precedes its own
    children (`sort_path` — see `v_dim_account`'s own comment in
    `schema.sql`) — the ordering `domain.accounts.build_account_tree`
    relies on to build the tree in one pass with no lookahead.
    `income_expense_only` narrows to the two P&L account types, same
    `WHERE` Income Statement has always used (Trial Balance/Balance
    Sheet/Variance's native-depth path want every type)."""
    sql = "SELECT * FROM v_dim_account WHERE is_active"
    if income_expense_only:
        sql += " AND account_type IN ('income', 'expense')"
    sql += " ORDER BY sort_path"
    return [dict(r) for r in conn.execute(text(sql)).mappings()]


def ledger_accounts(conn: Connection) -> list[dict]:
    """Every postable, active account — `id`/`code`/`name`/`account_type`
    only, ordered by type then code (same grouping order Trial Balance/
    Balance Sheet already use). Deliberately narrower than `dim_accounts`
    above (no parent/depth/path — the Ledger's own T-account cards are a
    flat grid, one per account, not a tree) and postable-only (a summary
    account never has its own postings to show a card for)."""
    rows = conn.execute(text(
        "SELECT id, code, name, account_type FROM accounts WHERE is_postable AND is_active "
        "ORDER BY account_type, code"
    )).mappings()
    return [dict(r) for r in rows]


def ledger_lines(conn: Connection, scenario: str, as_of: str) -> list[dict]:
    """Every individual debit/credit line posted in `scenario` on or
    before `as_of` — itemized, not aggregated, the one report in this
    module that needs real per-line detail rather than a balance.
    Ported from legacy `_ledger_rows`'s own plain SQL join, not modeled
    through a Postgres SRF: none of `fn_account_balances`/
    `fn_trial_balance`/`fn_rollup_balance`/`fn_cash_flow_lines` return
    itemized lines, and legacy itself never needed one either for what
    started as "a teaching aid, not a working report" (`ledger.html`'s
    own comment) — inventing one now would be manufacturing capability
    this feature never asked for, not porting behavior (`REBUILD.md`
    decision 4)."""
    rows = conn.execute(text("""
        SELECT l.account_id, l.debit, l.credit, e.entry_date, a.account_type
          FROM journal_lines l
          JOIN journal_entries e ON e.id = l.entry_id
          JOIN scenarios s ON s.id = e.scenario_id
          JOIN accounts a ON a.id = l.account_id
         WHERE s.code = :scenario AND e.entry_date <= :as_of
         ORDER BY l.account_id, e.entry_date, l.line_no
    """), {"scenario": scenario, "as_of": as_of}).mappings()
    return [dict(r) for r in rows]


def account_balances(conn: Connection, scenario: str, as_of: str | None = None,
                      since: str | None = None) -> dict[int, Decimal]:
    """`fn_account_balances(scenario, as_of[, from])` as an
    `{account_id: net}` map — every active account's own direct balance,
    leaf or summary, posted-to or not (unlike `fn_trial_balance`, which
    hides an untouched summary account). This is what
    `domain.accounts.build_account_tree` rolls up into a display tree;
    `since` (Postgres's `p_from`) scopes to one window (a fiscal year, a
    month-to-date) for the Current/Prior Year Earnings split Trial
    Balance and Balance Sheet both compute."""
    rows = conn.execute(
        text("SELECT * FROM fn_account_balances(:scenario, :as_of, :since)"),
        {"scenario": scenario, "as_of": as_of, "since": since},
    ).mappings()
    return {r["account_id"]: r["net"] for r in rows}


def rollup_balance(conn: Connection, scenario: str, level_depth: int,
                    as_of: str | None = None) -> list[dict]:
    """`fn_rollup_balance(scenario, level_depth, as_of)` — every posting
    collapsed onto whichever account sits at `level_depth` on its own
    path to the root, the SQL-side aggregation Variance's rolled-up mode
    needs (a Budget scenario posted straight to "Bank" reconciled
    against Actual's separate Checking/Savings postings)."""
    rows = conn.execute(
        text("SELECT * FROM fn_rollup_balance(:scenario, :level_depth, :as_of)"),
        {"scenario": scenario, "level_depth": level_depth, "as_of": as_of},
    ).mappings()
    return [dict(r) for r in rows]


def cash_flow_lines(conn: Connection, scenario: str, date_from: str | None = None,
                     date_to: str | None = None) -> list[dict]:
    """`fn_cash_flow_lines(scenario, from, to)` — the finest-grained cash
    flow artifact, one row per (transaction, non-cash contra account),
    already sign-flipped into "cash impact" terms. Everything the
    statement shows is presentation on top of this raw truth; see
    `service.cash_flow_rows`'s own module comment for the three grouping
    rules applied to it."""
    rows = conn.execute(
        text("SELECT * FROM fn_cash_flow_lines(:scenario, :date_from, :date_to)"),
        {"scenario": scenario, "date_from": date_from, "date_to": date_to},
    ).mappings()
    return [dict(r) for r in rows]


def cash_leg_net(conn: Connection, scenario: str, date_from: str | None,
                  date_to: str | None) -> Decimal:
    """Net posted amount on every `is_cashflow` leg of every transaction
    `fn_cash_flow_lines` itself considered in scope for this window — one
    of the tie-out's three independently-computed numbers (see
    `service.cash_flow_tie_out`'s own docstring for why three, not one)."""
    row = conn.execute(text("""
        SELECT COALESCE(SUM(f.amount), 0) AS net
          FROM v_fact_lines f JOIN accounts a ON a.id = f.account_id
         WHERE a.is_cashflow AND f.scenario_code = :scenario
           AND f.entry_date <= COALESCE(:date_to, 'infinity'::date)
           AND f.entry_date >= COALESCE(:date_from, '-infinity'::date)
           AND f.entry_id IN (SELECT DISTINCT entry_id
                                 FROM fn_cash_flow_lines(:scenario, :date_from, :date_to))
    """), {"scenario": scenario, "date_from": date_from, "date_to": date_to}).mappings().one()
    return row["net"]


def cashflow_accounts_balance(conn: Connection, scenario: str, as_of: str | None) -> Decimal:
    """Sum of `fn_account_balances(scenario, as_of)` restricted to
    `is_cashflow` accounts — the plain balance-sheet roll-forward figure
    (beginning or ending, depending on `as_of`) the tie-out's third
    number is built from."""
    row = conn.execute(text("""
        SELECT COALESCE(SUM(net), 0) AS net FROM fn_account_balances(:scenario, :as_of)
         WHERE account_id IN (SELECT id FROM accounts WHERE is_cashflow)
    """), {"scenario": scenario, "as_of": as_of}).mappings().one()
    return row["net"]


def flagged_cash_flow_entries(conn: Connection, scenario: str, date_from: str | None,
                               date_to: str | None) -> list[dict]:
    """Distinct transactions with more than one cash leg in this window
    (checking + savings both funded from one payroll deposit, say) — the
    attribution `fn_cash_flow_lines` already does divides these
    correctly, but the spec asks that they surface for a human glance
    anyway rather than blend in silently."""
    rows = conn.execute(text("""
        SELECT DISTINCT e.id, e.entry_date, e.description, p.name AS payee
          FROM journal_entries e
          LEFT JOIN payees p ON p.id = e.payee_id
         WHERE e.id IN (SELECT entry_id FROM fn_cash_flow_lines(:scenario, :date_from, :date_to)
                          WHERE n_cash_legs > 1)
         ORDER BY e.entry_date, e.id
    """), {"scenario": scenario, "date_from": date_from, "date_to": date_to}).mappings()
    return [dict(r) for r in rows]


def full_scenarios(conn: Connection) -> list[dict]:
    """`code`/`income_statement_only`/`is_staging` for every scenario —
    the narrow slice `service.compute_variance` needs to pick a default
    `compare` scenario and exclude Staging/income-statement-only ones
    from consideration. Deliberately not the full `scenarios.*` +
    `base_level_name` + `entry_count` shape legacy `scenarios_all()`
    returns (used far beyond reports, e.g. every scenario picker) — that
    belongs to `modules/reference/` (Phase 1.9) once it exists; reports
    stays deletable on its own until then rather than reaching into a
    module that isn't built yet."""
    rows = conn.execute(text(
        "SELECT code, income_statement_only, is_staging FROM scenarios ORDER BY scenario_type, code"
    )).mappings()
    return [dict(r) for r in rows]


def scenario_by_code(conn: Connection, code: str) -> dict | None:
    """`id`/`income_statement_only` for one scenario code, or `None` if
    it doesn't exist — `service.income_statement_balances`' own check for
    whether to read journal facts or `budget_lines`."""
    row = conn.execute(
        text("SELECT id, income_statement_only FROM scenarios WHERE code = :code"),
        {"code": code},
    ).mappings().first()
    return dict(row) if row else None


def scenario_base_level(conn: Connection, code: str) -> dict | None:
    """`id`/`depth` of the scenario's own `base_level_id` account level,
    or `None` if it has none — Variance's default rollup granularity when
    the user hasn't picked a level explicitly (the natural granularity
    the compare scenario was actually entered at)."""
    row = conn.execute(text("""
        SELECT al.id, al.depth FROM scenarios s
          JOIN account_levels al ON al.id = s.base_level_id
         WHERE s.code = :code
    """), {"code": code}).mappings().first()
    return dict(row) if row else None


def account_level_depth(conn: Connection, level_id: int) -> int | None:
    """The `depth` a given `account_levels.id` sits at, or `None` if it
    doesn't exist — resolves Variance's `level_id` query param into the
    `p_depth` `fn_rollup_balance` actually wants."""
    row = conn.execute(
        text("SELECT depth FROM account_levels WHERE id = :level_id"), {"level_id": level_id}
    ).mappings().first()
    return row["depth"] if row else None


def postable_flags(conn: Connection) -> dict[int, bool]:
    """`{account_id: is_postable}` for every account — Variance's rolled-
    up rows use `not is_postable` as their `has_children` signal (a
    rolled-up row's own target account is very often a summary account,
    not a postable one; see `service.compute_variance`'s own comment)."""
    rows = conn.execute(text("SELECT id, is_postable FROM accounts")).mappings()
    return {r["id"]: r["is_postable"] for r in rows}


def budget_line_totals(conn: Connection, scenario_id: int, date_from: str | None,
                        date_to: str | None) -> dict[int, Decimal]:
    """`{account_id: sum(amount)}` from `budget_lines` for one
    income-statement-only scenario, restricted to whichever months the
    range touches — the only balance source such a scenario has, since
    it never takes a journal entry at all (`fn_income_statement_only_
    guard` blocks it).

    A real, previously-undiscovered bug lived here until Phase 4.1's own
    Income Statement screen was the first caller to ever exercise a
    Compare-to against an income-statement-only (budget) scenario:
    `:date_from::date` — a bind param immediately followed by Postgres's
    `::` cast operator, no space between — reads to SQLAlchemy's `text()`
    parser as something other than a plain `:date_from` bind param, so
    the literal string `:date_from::date` reached Postgres unsubstituted
    and failed with a syntax error. Contrast `cash_leg_net`'s own
    `COALESCE(:date_to, 'infinity'::date)` a few functions up in this
    same file — its `::date` casts a literal, never sits directly after
    a bind param name, so it never tripped this. Fixed with a space
    before the cast (`:date_from ::date`) — Postgres allows the
    whitespace, and it's enough for SQLAlchemy to find the param
    boundary correctly. No test in `backend/tests/` ever called this
    function with both a real `date_from`/`date_to` and a real
    Postgres connection until now — `budget_line_totals` had no test of
    its own at all before this fix's own test."""
    where, params = ["scenario_id = :scenario_id"], {"scenario_id": scenario_id}
    if date_from:
        where.append("period_month >= date_trunc('month', :date_from ::date)")
        params["date_from"] = date_from
    if date_to:
        where.append("period_month <= date_trunc('month', :date_to ::date)")
        params["date_to"] = date_to
    rows = conn.execute(text(
        f"SELECT account_id, SUM(amount) AS amt FROM budget_lines WHERE {' AND '.join(where)} "
        "GROUP BY account_id"
    ), params).mappings()
    return {r["account_id"]: r["amt"] for r in rows}
