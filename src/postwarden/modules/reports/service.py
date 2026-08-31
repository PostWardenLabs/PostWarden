"""Report assembly — the genuinely hard parts
(`_income_statement_matrix`/`_scale_income_statement_result`,
`_cash_flow_rows`/`_cash_flow_tie_out`, `_compute_variance`), plus the
"mechanical" wrapper functions (`_trial_balance_rows`,
`_balance_sheet_rows`, `_income_statement_rows`/
`_income_statement_balances`) those hard functions and `router.py`'s
routes both need to actually run. Pure helpers with no framework/IO
imports (`build_account_tree`/`flatten_tree`, `split_periods`,
`income_statement_groups`) live in `domain/` instead, not here.

Every function here takes a SQLAlchemy `Connection` (from
`db.get_connection()`, same as every other module) as its first
argument and reads through `repository.py` — never raw SQL of its own.
Reports keep calling the existing Postgres SRFs directly rather than
modeling them through SQLAlchemy Core; `repository.py` is where that
happens.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.engine import Connection

from ...domain.accounts import (
    ACCOUNT_TYPES,
    TYPE_LABELS,
    build_account_tree,
    earnings_rows,
    flatten_tree,
    income_statement_groups,
    pnl_net,
)
from ...domain.money import divide, pct_of, pct_variance, variance_amount
from . import repository as repo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------


def trial_balance(conn: Connection, scenario: str, as_of: str | None, zeros: int, raw: int = 0) -> dict:
    """Ported from `app/main.py`'s `_trial_balance_rows`, unchanged in
    shape. `raw` shows every account at its own all-time balance with no
    Current/Prior Year Earnings split (the "raw ledger" view); the
    default splits P&L into those two synthetic Equity rows the way a
    real close would, without actually closing anything (SPEC.md decision
    on no physical period-close)."""
    as_of_date = as_of or None
    as_of_dt = date.fromisoformat(as_of_date) if as_of_date else date.today()
    accounts = repo.dim_accounts(conn)
    full_balances = repo.account_balances(conn, scenario, as_of_date)
    total_debits = sum((max(v, 0) for v in full_balances.values()), Decimal(0))
    total_credits = sum((max(-v, 0) for v in full_balances.values()), Decimal(0))

    def build_sections(balances_by_id: dict, extra_equity: list[dict]) -> list[dict]:
        roots = build_account_tree(accounts, balances_by_id)
        grouped = []
        for t in ACCOUNT_TYPES:
            type_roots = [r for r in roots if r["account_type"] == t]
            extra = extra_equity if t == "equity" else []
            # Only `extra`'s own root ("Retained Earnings") goes into the
            # sub_debits/sub_credits sum, not its two children too —
            # `earnings_rows()` gives the parent a rolled-up total that
            # already includes both, so summing all three would double-
            # count the same money, the same reason `type_roots` (roots,
            # not the post-flatten `flat` list) is what's summed for real
            # accounts a few lines below.
            extra_roots = [r for r in extra if r["parent_id"] is None]
            flat = flatten_tree(type_roots, zeros)
            if flat or extra:
                grouped.append({
                    "type": t, "label": TYPE_LABELS[t], "rows": flat + extra,
                    "sub_debits": sum((r["debit_balance"] for r in type_roots + extra_roots), Decimal(0)),
                    "sub_credits": sum((r["credit_balance"] for r in type_roots + extra_roots), Decimal(0)),
                    "show_type_total": len(type_roots) > 1 or bool(extra),
                })
        return grouped

    if raw:
        grouped = build_sections(full_balances, [])
        return {"grouped": grouped, "total_debits": total_debits, "total_credits": total_credits,
                "in_balance": total_debits == total_credits}

    fy_start = date(as_of_dt.year, 1, 1).isoformat()
    month_start = date(as_of_dt.year, as_of_dt.month, 1).isoformat()
    fy_balances = repo.account_balances(conn, scenario, as_of_date, fy_start)
    mtd_balances = repo.account_balances(conn, scenario, as_of_date, month_start)

    all_time_earnings = pnl_net(accounts, full_balances)
    fy_earnings = pnl_net(accounts, fy_balances)
    mtd_earnings = pnl_net(accounts, mtd_balances)
    prior_year_earnings = all_time_earnings - fy_earnings
    current_year_earnings = fy_earnings - mtd_earnings

    merged_balances = {a["id"]: (mtd_balances.get(a["id"], 0)
                                  if a["account_type"] in ("income", "expense")
                                  else full_balances.get(a["id"], 0))
                        for a in accounts}
    extra_equity = earnings_rows(current_year_earnings, prior_year_earnings, bool(zeros))
    grouped = build_sections(merged_balances, extra_equity)

    return {"grouped": grouped, "total_debits": total_debits, "total_credits": total_credits,
            "in_balance": total_debits == total_credits, "fy_start": fy_start,
            "month_start": month_start}


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------


def balance_sheet(conn: Connection, scenario: str, as_of: str | None, raw: int = 0, zeros: int = 0) -> dict:
    """No MTD carve-out here, unlike trial_balance: a balance sheet has
    no Income/Expense section of its own to hold that money in, so
    "Current Year" has to mean the *whole* fiscal year to date (MTD
    included) or Assets would stop reconciling against Liabilities +
    Equity by exactly the MTD amount.

    Unlike Trial Balance, `raw` here doesn't just change what Income/
    Expense's own section shows — Balance Sheet has no such section at
    all, so there's nowhere else for that money to be visible. `raw=1`
    therefore drops the "Retained Earnings" plug entirely rather than
    collapsing it to one merged line: Assets keeps reflecting every
    posted transaction same as always, but Liabilities + Equity no
    longer includes the not-yet-closed P&L that real-world Assets side
    already absorbed, so the two genuinely stop reconciling by exactly
    `total_pnl` — `in_balance` goes `False` and the page says so. That's
    deliberate, not a bug to "fix" by re-adding a plug under a different
    name: it's what a balance sheet actually looks like before a real
    close, which PostWarden never performs (SPEC.md decision 10)."""
    as_of_date = as_of or None
    as_of_dt = date.fromisoformat(as_of_date) if as_of_date else date.today()
    accounts = repo.dim_accounts(conn)
    full_balances = repo.account_balances(conn, scenario, as_of_date)
    total_pnl = pnl_net(accounts, full_balances)

    if raw:
        earn_rows: list[dict] = []
        equity_plug = Decimal(0)
    else:
        fy_start = date(as_of_dt.year, 1, 1).isoformat()
        fy_balances = repo.account_balances(conn, scenario, as_of_date, fy_start)
        fy_earnings = pnl_net(accounts, fy_balances)
        prior_year_earnings = total_pnl - fy_earnings
        earn_rows = earnings_rows(fy_earnings, prior_year_earnings, bool(zeros))
        equity_plug = total_pnl

    roots = build_account_tree(accounts, full_balances)
    asset_roots = [r for r in roots if r["account_type"] == "asset"]
    liability_roots = [r for r in roots if r["account_type"] == "liability"]
    equity_roots = [r for r in roots if r["account_type"] == "equity"]
    assets = flatten_tree(asset_roots, zeros=zeros)
    liabilities = flatten_tree(liability_roots, zeros=zeros)
    # The "Retained Earnings" node (when present) is appended straight
    # onto the real equity rows, not returned as a separate field the
    # way `earnings_lines` used to be — it's a real collapsible tree
    # node now (see `earnings_rows()`'s own docstring), so it renders
    # through the exact same account-row component every real Equity
    # account already does, both here and in the CSV/XLSX exporters.
    equity = flatten_tree(equity_roots, zeros=zeros) + earn_rows

    total_assets = sum((r["subtotal"] for r in asset_roots), Decimal(0))
    total_liabilities = -sum((r["subtotal"] for r in liability_roots), Decimal(0))
    total_equity = -sum((r["subtotal"] for r in equity_roots), Decimal(0)) + equity_plug
    return {
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "total_assets": total_assets, "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "total_liab_and_equity": total_liabilities + total_equity,
        "in_balance": total_assets == total_liabilities + total_equity,
    }


def ledger_rows(conn: Connection, scenario: str, as_of: str | None, zeros: int = 0, raw: int = 0) -> dict:
    """The one report that shows itemized lines rather than an
    aggregated balance: one T-account card per postable account with
    activity (or every account, with `zeros`), each a paired list of its
    own debit/credit lines plus a running total. `raw` toggles the same
    simulated-monthly-close carve-out Trial Balance applies to Income/
    Expense accounts (drop any flow-account line dated before the
    as-of month's start), applied here per *line* rather than to an
    aggregate balance, since no existing repository function returns
    itemized lines (see `repository.ledger_lines`'s own docstring)."""
    as_of_date = as_of or date.today().isoformat()
    as_of_dt = date.fromisoformat(as_of_date)
    month_start = date(as_of_dt.year, as_of_dt.month, 1)

    accounts = repo.ledger_accounts(conn)
    lines = repo.ledger_lines(conn, scenario, as_of_date)

    lines_by_account: dict[int, list[dict]] = {}
    for ln in lines:
        if not raw and ln["account_type"] in ("income", "expense") and ln["entry_date"] < month_start:
            continue
        lines_by_account.setdefault(ln["account_id"], []).append(ln)

    def t_account(a: dict) -> dict | None:
        acct_lines = lines_by_account.get(a["id"], [])
        if not acct_lines and not zeros:
            return None
        # Each side keeps its own line's date alongside its amount
        # (BACKLOG.md's own ask) — a debit's date and the credit sitting
        # beside it are otherwise unrelated, same as a real T-account,
        # where the two sides are independent running lists that just
        # happen to share a page; pairing them by index is purely for
        # this card's own two-column layout, nothing more.
        debits = [(ln["entry_date"], ln["debit"]) for ln in acct_lines if ln["debit"]]
        credits = [(ln["entry_date"], ln["credit"]) for ln in acct_lines if ln["credit"]]
        net = sum((d for _, d in debits), Decimal(0)) - sum((c for _, c in credits), Decimal(0))
        rows = [{"debit_date": debits[i][0] if i < len(debits) else None,
                 "debit": debits[i][1] if i < len(debits) else None,
                 "credit": credits[i][1] if i < len(credits) else None,
                 "credit_date": credits[i][0] if i < len(credits) else None}
                for i in range(max(len(debits), len(credits)))]
        is_flow = a["account_type"] in ("income", "expense")
        return {"code": a["code"], "name": a["name"], "rows": rows,
                # The total row only writes to the Debit or Credit column
                # depending on the balance — a net debit balance shows in
                # Debit, a net credit balance in Credit, never both, and
                # neither at all for an exact wash (net == 0).
                "total_debit": net if net > 0 else None,
                "total_credit": -net if net < 0 else None,
                "link_date_from": "" if (raw or not is_flow) else month_start.isoformat()}

    grouped = []
    for t in ACCOUNT_TYPES:
        rows = [ta for a in accounts if a["account_type"] == t
                for ta in [t_account(a)] if ta is not None]
        if rows:
            grouped.append({"label": TYPE_LABELS[t], "rows": rows})
    return {"grouped": grouped, "as_of": as_of_date, "month_start": month_start.isoformat()}


# ---------------------------------------------------------------------------
# Income statement — single range, then the Split-view matrix built on
# top of it.
# ---------------------------------------------------------------------------


def income_statement_balances(conn: Connection, scenario_code: str, accounts_by_id: dict,
                               date_to_v: str | None, date_from_v: str | None) -> dict:
    """Ported from `app/main.py`'s `_income_statement_balances`. Account
    balances for one side of the Income Statement (base or compare) —
    journal-based via `fn_account_balances` for a normal scenario, same
    as every other report, but an income-statement-only scenario
    (Budget Grid's own scenario type) never takes a journal entry at all
    (`fn_income_statement_only_guard` blocks it), so that path always
    came back empty — the Compare column silently showing nothing was
    actually correct given what it was querying, just not what "compare
    to a budget scenario" should mean. Its numbers live in `budget_lines`
    instead, one row per (account, month); summed across every month the
    report's date range touches, since Income Statement (unlike Budget
    Grid) covers an arbitrary range, not one month at a time.
    `budget_lines.amount` is a plain positive target with no debit/credit
    sign to it, flipped here into the same journal sign convention
    `fn_account_balances` returns (income negative) — the `sign` flip
    `income_statement_groups()` applies next expects that convention from
    either source equally."""
    scen = repo.scenario_by_code(conn, scenario_code)
    if not scen:
        return {}
    if not scen["income_statement_only"]:
        return repo.account_balances(conn, scenario_code, date_to_v, date_from_v)
    rows = repo.budget_line_totals(conn, scen["id"], date_from_v, date_to_v)
    return {
        account_id: (-1 if accounts_by_id.get(account_id, {}).get("account_type") == "income" else 1) * amt
        for account_id, amt in rows.items()
    }


def income_statement_rows(conn: Connection, scenario: str, date_from: str, date_to: str,
                           compare: str = "", zeros: int = 0, pct_of_base: bool = False) -> dict:
    """Ported from `app/main.py`'s `_income_statement_rows`, unchanged in
    shape."""
    date_to_v, date_from_v = date_to or None, date_from or None
    accounts = repo.dim_accounts(conn, income_expense_only=True)
    accounts_by_id = {a["id"]: a for a in accounts}
    base_by_id = income_statement_balances(conn, scenario, accounts_by_id, date_to_v, date_from_v)
    compare_by_id = (income_statement_balances(conn, compare, accounts_by_id, date_to_v, date_from_v)
                      if compare else {})
    roots = build_account_tree(accounts, base_by_id, compare_by_id)
    groups_income = income_statement_groups(roots, "income", flip=True, zeros=zeros, pct_of_base=pct_of_base)
    groups_expense = income_statement_groups(roots, "expense", flip=False, zeros=zeros, pct_of_base=pct_of_base)

    total_base_income = sum((g["base_subtotal"] for g in groups_income), Decimal(0))
    total_compare_income = sum((g["compare_subtotal"] for g in groups_income), Decimal(0))
    income_variance_amount = variance_amount(total_base_income, total_compare_income, pct_of_base)
    income_variance = pct_variance(total_base_income, total_compare_income, pct_of_base)

    base_running, compare_running = total_base_income, total_compare_income
    for g in groups_expense:
        base_running -= g["base_subtotal"]
        compare_running -= g["compare_subtotal"]
        g["base_running_after"] = base_running
        g["compare_running_after"] = compare_running
        g["running_variance"] = variance_amount(base_running, compare_running, pct_of_base)
        g["running_pct_variance"] = pct_variance(base_running, compare_running, pct_of_base)
        g["base_pct_of_income"] = pct_of(g["base_subtotal"], total_base_income)
        g["compare_pct_of_income"] = pct_of(g["compare_subtotal"], total_compare_income)
        g["base_running_pct_of_income"] = pct_of(base_running, total_base_income)
        g["compare_running_pct_of_income"] = pct_of(compare_running, total_compare_income)

    net_income = base_running if groups_expense else total_base_income
    compare_net_income = compare_running if groups_expense else total_compare_income
    return {
        "income_groups": groups_income, "expense_groups": groups_expense,
        "total_base_income": total_base_income, "total_compare_income": total_compare_income,
        "income_variance_amount": income_variance_amount, "income_variance": income_variance,
        "net_income": net_income, "compare_net_income": compare_net_income,
        "net_income_variance_amount": variance_amount(net_income, compare_net_income, pct_of_base),
        "net_income_variance": pct_variance(net_income, compare_net_income, pct_of_base),
        "net_income_pct_of_income": pct_of(net_income, total_base_income),
        "compare_net_income_pct_of_income": pct_of(compare_net_income, total_compare_income),
        "has_compare": bool(compare),
    }


def scale_income_statement_result(result: dict, n: int) -> dict:
    """Ported from `app/main.py`'s `_scale_income_statement_result`,
    unchanged. The Average column's own figures — the Totals column's
    exact figures divided by the real period count `n`. Safe/exact as a
    plain division rather than a fresh computation because every dollar
    amount here is additive across periods (Totals.base_net already
    equals sum(period.base_net for period in periods) — Split's periods
    partition the date range with no overlap or gap), and every
    percentage/ratio field (pct_variance, income_variance,
    *_pct_of_income, ...) is scale-invariant: dividing both the amount
    and whatever it's a ratio *of* by the same n leaves the ratio
    identical to what Totals already computed — recomputing it from the
    divided figures would just be extra work to land on the exact same
    number. So only the plain dollar fields get divided here; every
    percentage field is carried through unchanged via the row/group
    dict's own shallow copy.

    Pure — no DB, no repository call — but kept here rather than in
    `domain/` for cohesion with `income_statement_matrix` right below,
    the one function that calls it."""
    def scale_row(r):
        return {**r, "base_net": divide(r["base_net"], n), "compare_net": divide(r["compare_net"], n),
                "variance": divide(r["variance"], n)}

    def scale_group(g, is_expense):
        g2 = {**g, "rows": [scale_row(r) for r in g["rows"]],
              "base_subtotal": divide(g["base_subtotal"], n), "compare_subtotal": divide(g["compare_subtotal"], n),
              "variance": divide(g["variance"], n)}
        if is_expense:
            g2["base_running_after"] = divide(g["base_running_after"], n)
            g2["compare_running_after"] = divide(g["compare_running_after"], n)
            g2["running_variance"] = divide(g["running_variance"], n)
        return g2

    return {
        **result,
        "income_groups": [scale_group(g, False) for g in result["income_groups"]],
        "expense_groups": [scale_group(g, True) for g in result["expense_groups"]],
        "total_base_income": divide(result["total_base_income"], n),
        "total_compare_income": divide(result["total_compare_income"], n),
        "income_variance_amount": divide(result["income_variance_amount"], n),
        "net_income": divide(result["net_income"], n),
        "compare_net_income": divide(result["compare_net_income"], n),
        "net_income_variance_amount": divide(result["net_income_variance_amount"], n),
    }


def income_statement_matrix(conn: Connection, scenario: str, periods: list[dict], date_from: str, date_to: str,
                             compare: str = "", zeros: int = 0, pct_of_base: bool = False) -> dict:
    """Split-view counterpart to `income_statement_rows()` above — one
    column group per Split period instead of one range. A thin
    wrapper around that same single-period function rather than a
    parallel calculation: every period gets its own full
    `income_statement_rows()` call with `zeros` forced on, which
    guarantees every account row/group exists in every period, aligned by
    account id — a plain lookup merge from there, with no risk of August
    ending up with a different set of rows than September because one had
    a zero-balance account the other didn't.

    A separate "combined activity" tree (the same `build_account_tree`/
    `income_statement_groups` machinery the single-period report already
    uses) decides which rows/groups actually render under the *real*
    `zeros` flag — fed the sum of |base_net| and |compare_net| across
    every real period (the Totals column below deliberately never
    contributes to this — see there), so a row shows if it had activity
    in *any* period and hides only if it was zero everywhere, the same
    meaning "show zero balances" already has today, just extended across
    the whole matrix instead of one range. The scaffold tree's own
    base_net/compare_net figures are otherwise meaningless (a sum of
    absolute values, not a real total) — every row/group below gets its
    *real* per-period numbers overlaid from `per_period` right after,
    keyed by account id either way (a group's own id is its root
    account's — rows[0]).

    A trailing "Totals" column — the same whole-range figures the
    unsplit report would show for this exact scenario/date_from/date_to —
    is appended after the real periods, same shape as any other period
    (its own `income_statement_rows()` call, zeros forced on) so a caller
    iterating `periods` needs no special casing. Its label is a plain,
    frontend-rewritable default — the caller learns only the
    date_from/date_to it resolved to, not which preset (if any) was
    picked. Average follows right after Totals, same treatment — see
    `scale_income_statement_result()`.
    """
    accounts = repo.dim_accounts(conn, income_expense_only=True)
    per_period = [
        income_statement_rows(conn, scenario, p["date_from"], p["date_to"], compare, zeros=1,
                               pct_of_base=pct_of_base)
        for p in periods
    ]

    combined_base, combined_compare, period_rows_by_id = {}, {}, []
    for p in per_period:
        rows_by_id = {}
        for g in p["income_groups"] + p["expense_groups"]:
            for r in g["rows"]:
                rows_by_id[r["id"]] = r
                combined_base[r["id"]] = combined_base.get(r["id"], 0) + abs(r["base_net"])
                combined_compare[r["id"]] = combined_compare.get(r["id"], 0) + abs(r["compare_net"])
        period_rows_by_id.append(rows_by_id)

    roots = build_account_tree(accounts, combined_base, combined_compare)
    groups_income = income_statement_groups(roots, "income", flip=True, zeros=zeros, pct_of_base=pct_of_base)
    groups_expense = income_statement_groups(roots, "expense", flip=False, zeros=zeros, pct_of_base=pct_of_base)

    # The Totals column: whole-range figures, appended as one more
    # "period" after the union check above (see the docstring's own
    # paragraph on why it never contributes to it).
    totals_result = income_statement_rows(conn, scenario, date_from, date_to, compare, zeros=1,
                                           pct_of_base=pct_of_base)
    totals_rows_by_id = {r["id"]: r for g in totals_result["income_groups"] + totals_result["expense_groups"]
                          for r in g["rows"]}
    period_rows_by_id.append(totals_rows_by_id)

    # Average: Totals' own figures divided by the real period count — see
    # scale_income_statement_result's own docstring for why a plain
    # division is exact here rather than an approximation. Same "just one
    # more period" treatment as Totals, appended right after it.
    average_result = scale_income_statement_result(totals_result, len(periods))
    average_rows_by_id = {r["id"]: r for g in average_result["income_groups"] + average_result["expense_groups"]
                           for r in g["rows"]}
    period_rows_by_id.append(average_rows_by_id)

    all_periods = per_period + [totals_result, average_result]
    periods_with_total = periods + [
        {"label": "Total", "date_from": date_from, "date_to": date_to, "partial": False, "is_total": True},
        {"label": "Average", "date_from": date_from, "date_to": date_to, "partial": False, "is_average": True},
    ]

    # Matched by the group's own root-account id (its rows[0], same as any
    # other row) within its own income/expense list specifically — not by
    # name, and not a combined search across both lists: two top-level
    # accounts sharing a name (nothing stops a user naming both an income
    # and an expense root "Adjustments") would otherwise risk a group
    # matching the wrong one.
    for scaffold_groups, key in ((groups_income, "income_groups"), (groups_expense, "expense_groups")):
        for g in scaffold_groups:
            root_id = g["rows"][0]["id"]
            for r in g["rows"]:
                r["periods"] = [rows_by_id.get(r["id"], {}) for rows_by_id in period_rows_by_id]
            g["periods"] = [next(pg for pg in p[key] if pg["rows"][0]["id"] == root_id) for p in all_periods]

    return {
        "income_groups": groups_income, "expense_groups": groups_expense,
        # Each entry is a *whole* single-period income_statement_rows()
        # result (total_base_income, net_income, ... — every top-level
        # figure the unsplit result carries), kept as-is rather than
        # reshaped, so a caller reads periods_totals[i].x the same way
        # the unsplit result reads x directly. The last two entries are
        # the Totals and Average columns' own results.
        "periods_totals": all_periods,
        "has_compare": bool(compare),
        "periods": periods_with_total,
    }


# ---------------------------------------------------------------------------
# Cash flow statement — flat (no operating/investing/financing split, out
# of scope per SPEC.md decision 20), grouped by the contra-account each
# cash leg attributes to. fn_cash_flow_lines (db/schema.sql) does the
# real per-transaction attribution at full granularity (every non-cash
# leg, its own posted amount, sign-flipped — nothing netted or bucketed
# at the SQL layer); everything here is presentation on top of that raw
# truth — grouping rows into inflows/outflows, peeling equity-contra legs
# into their own "ledger adjustments" section, folding a reducible
# income entry's deduction legs into its own income row, and running the
# three-way tie-out the spec calls a hard invariant. See SPEC.md decision
# 20's addenda for the reasoning behind each of these three presentation
# rules — the underlying per-leg numbers this all runs on never change.
# ---------------------------------------------------------------------------


def cash_flow_tie_out(conn: Connection, scenario: str, date_from_v: str | None, date_to_v: str | None,
                       statement_total) -> dict:
    """Ported from `app/main.py`'s `_cash_flow_tie_out`, unchanged in
    shape. The three numbers the spec says must agree to the cent: the
    statement's own total, the net leg activity on `is_cashflow` accounts
    for the same (post-exclusion) set of transactions, and the plain
    balance-sheet roll-forward (ending − beginning) of those same
    accounts. A mismatch means an untagged/mistagged account, a bad split
    attribution, or a pure-transfer wrongly included/excluded — surfaced
    as a warning in the report result and logged, per the spec, rather
    than silently shown as if nothing were wrong.

    beginning/ending are returned (not just balance_delta) so a caller
    can show them unconditionally as their own lines — previously they
    were computed here but only ever surfaced inside the failure banner,
    so a passing report gave no grounding for what "net change" was a
    change *from*. Presentation-layer bucketing (ledger adjustments,
    netting) never touches this function or its inputs: statement_total
    is still literally the same net_change number it always was, and
    beginning/ending are still the plain balance-sheet roll-forward,
    independent of how the statement chooses to group its rows."""
    cash_leg_net = repo.cash_leg_net(conn, scenario, date_from_v, date_to_v)

    # Beginning balance is "as of the day before date_from", cumulative
    # since inception — the same balance a Balance Sheet run as of that
    # day would show. No date_from means the range is unbounded at the
    # start, so there's nothing before it to roll forward from.
    if date_from_v:
        begin_as_of = (date.fromisoformat(date_from_v) - timedelta(days=1)).isoformat()
        beginning = repo.cashflow_accounts_balance(conn, scenario, begin_as_of)
    else:
        beginning = Decimal(0)
    ending = repo.cashflow_accounts_balance(conn, scenario, date_to_v)
    balance_delta = ending - beginning

    ok = statement_total == cash_leg_net == balance_delta
    if not ok:
        logger.error(
            "Cash flow tie-out mismatch (scenario=%s, %s..%s): "
            "statement_total=%s cash_leg_net=%s balance_delta=%s",
            scenario, date_from_v, date_to_v, statement_total, cash_leg_net, balance_delta,
        )
    return {"ok": ok, "statement_total": statement_total, "cash_leg_net": cash_leg_net,
            "balance_delta": balance_delta, "beginning": beginning, "ending": ending}


def cash_flow_rows(conn: Connection, scenario: str, date_from: str, date_to: str) -> dict:
    """Ported from `app/main.py`'s `_cash_flow_rows`, unchanged in shape.
    Groups `fn_cash_flow_lines`' raw per-leg rows into the report's three
    sections. Three routing rules apply, per entry, in this order — see
    SPEC.md decision 20's addenda for the full reasoning behind each:

      1. Equity-typed contra legs are always their own row, always in
         ledger_adjustments — never blended into inflows/outflows, and
         never excluded outright either (excluding them would break the
         tie-out's beginning+net_change==ending identity, since the cash
         genuinely did move; the fix is presentation, not deletion).
         Peeled off first so they can't interact with rule 2.

      2. Among what's left on that same entry: if there is exactly one
         income-typed leg and at least one expense-typed leg, they
         collapse into a single row under the income leg's own account —
         amount is their signed sum, which (the entry balances, so this
         is exact, not estimated) already equals that leg group's own
         net cash contribution. The folded-away expense legs ride along
         as that row's netted_from, so the detail is demoted to an
         annotation, not deleted — still reachable, just not cluttering
         the top-level view. Two or more income legs on one entry is
         deliberately left un-netted: there's no principled way to
         decide which income leg a shared deduction belongs to, so
         rather than guess, every leg itemizes on its own, same as if
         rule 2 had never fired.

      3. Everything else — asset/liability legs always, plus any
         income/expense leg rule 2 didn't consume — itemizes exactly as
         fn_cash_flow_lines returned it, unchanged from before this rule
         existed.
    """
    date_from_v = date_from or None
    date_to_v = date_to or None
    lines = repo.cash_flow_lines(conn, scenario, date_from_v, date_to_v)
    accounts_by_id = {a["id"]: a for a in repo.dim_accounts(conn)}

    by_entry: dict[str, list[dict]] = {}
    for l in lines:
        by_entry.setdefault(l["entry_id"], []).append(l)

    def bump(agg: dict, account_id: int, amount, flagged: bool, netted_from: dict | None = None):
        row = agg.setdefault(account_id, {"amount": Decimal(0), "flagged": False, "netted_from": {}})
        row["amount"] += amount
        row["flagged"] = row["flagged"] or flagged
        for nf_id, nf_amount in (netted_from or {}).items():
            row["netted_from"][nf_id] = row["netted_from"].get(nf_id, 0) + nf_amount

    activity: dict[int, dict] = {}     # real economic activity -> inflows/outflows
    adjustments: dict[int, dict] = {}  # equity-contra -> ledger adjustments
    for entry_id, entry_lines in by_entry.items():
        flagged = any(l["n_cash_legs"] > 1 for l in entry_lines)
        by_type: dict[str, list[dict]] = {}
        for l in entry_lines:
            a = accounts_by_id.get(l["contra_account_id"])
            if a:
                by_type.setdefault(a["account_type"], []).append(l)

        # Rule 1 — equity, always its own row, always ledger_adjustments.
        for l in by_type.pop("equity", []):
            bump(adjustments, l["contra_account_id"], l["amount"], flagged)

        # Rule 2 — fold expense legs into a single well-defined income leg.
        income_legs = by_type.pop("income", [])
        expense_legs = by_type.pop("expense", [])
        if len(income_legs) == 1 and expense_legs:
            inc = income_legs[0]
            total = inc["amount"] + sum((e["amount"] for e in expense_legs), Decimal(0))
            netted_from = {e["contra_account_id"]: e["amount"] for e in expense_legs}
            bump(activity, inc["contra_account_id"], total, flagged, netted_from)
        else:
            for l in income_legs + expense_legs:
                bump(activity, l["contra_account_id"], l["amount"], flagged)

        # Rule 3 — everything left (asset/liability) itemizes as-is.
        for l in [x for legs in by_type.values() for x in legs]:
            bump(activity, l["contra_account_id"], l["amount"], flagged)

    def to_rows(agg: dict) -> list[dict]:
        out = []
        for account_id, r in agg.items():
            a = accounts_by_id.get(account_id)
            if not a:
                continue
            netted_from = sorted((
                {"account_code": accounts_by_id[nf_id]["code"],
                 "account_name": accounts_by_id[nf_id]["name"], "amount": nf_amount}
                for nf_id, nf_amount in r["netted_from"].items() if nf_id in accounts_by_id
            ), key=lambda n: n["account_code"])
            out.append({"account_id": account_id, "account_code": a["code"], "account_name": a["name"],
                        "parent_path": a["parent_path"], "amount": r["amount"],
                        "flagged": r["flagged"], "netted_from": netted_from})
        out.sort(key=lambda r: r["account_code"])
        return out

    activity_rows = to_rows(activity)
    inflows = [r for r in activity_rows if r["amount"] >= 0]
    outflows = [r for r in activity_rows if r["amount"] < 0]
    ledger_adjustments = to_rows(adjustments)

    total_inflows = sum((r["amount"] for r in inflows), Decimal(0))
    total_outflows = sum((r["amount"] for r in outflows), Decimal(0))
    total_adjustments = sum((r["amount"] for r in ledger_adjustments), Decimal(0))
    # Unchanged from before rules 1/2 existed: still every non-cash leg's
    # own contribution summed once. Rules 1/2 only ever regroup rows that
    # already summed to the same total, so this, the tie-out, and the
    # beginning+net_change==ending identity are all exactly as before.
    net_change = total_inflows + total_outflows + total_adjustments

    flagged_entries = repo.flagged_cash_flow_entries(conn, scenario, date_from_v, date_to_v)

    return {
        "inflows": inflows, "outflows": outflows, "ledger_adjustments": ledger_adjustments,
        "total_inflows": total_inflows, "total_outflows": total_outflows,
        "total_adjustments": total_adjustments,
        "net_change": net_change, "flagged_entries": flagged_entries,
        "tie_out": cash_flow_tie_out(conn, scenario, date_from_v, date_to_v, net_change),
    }


# ---------------------------------------------------------------------------
# Variance — budget (or any scenario) vs. actual (or any other scenario),
# rolled up to a common level so a coarse scenario (posted straight to
# "Bank") lines up against a fine one (Checking + Savings) instead of
# just not matching up at all. Scoped to full scenarios only — an
# income-statement-only one never has the journal-entry facts this reads,
# by design; see the Budget grid for that comparison instead.
# ---------------------------------------------------------------------------


def compute_variance(conn: Connection, baseline: str, compare: str, level_id: str, as_of: str | None,
                      zeros: int = 0, pct_of_base: bool = False) -> dict:
    """Shared by the variance report and its CSV export — same rollup,
    same baseline/compare resolution, so the export matches what's on
    screen. Excludes Staging same as income-statement-
    only scenarios: Staging is a layover for entries waiting on approval,
    not a real balance sheet a user would ever want to compare against —
    whatever happens to be sitting there is incidental and temporary, not
    information worth reading a variance off of."""
    scens = [s for s in repo.full_scenarios(conn) if not s["income_statement_only"] and not s["is_staging"]]
    codes = [s["code"] for s in scens]
    if not compare:
        others = [s["code"] for s in scens if s["code"] != baseline]
        compare = others[0] if others else ""

    level_depth = None
    if level_id:
        level_depth = repo.account_level_depth(conn, int(level_id))
    elif compare:
        # Default to the comparison scenario's own base level, if it has
        # one — the natural granularity it was actually entered at. Set
        # level_id too (not just level_depth) so a caller's picker
        # reflects what was actually used instead of silently showing
        # "no rollup".
        bl = repo.scenario_base_level(conn, compare)
        if bl:
            level_depth = bl["depth"]
            level_id = str(bl["id"])

    as_of_date = as_of or None

    if level_depth is None:
        # Native depth — build a real account tree (same
        # build_account_tree/flatten_tree Trial Balance/Balance Sheet/
        # Income Statement use) instead of fn_rollup_balance(scenario,
        # NULL, ...), which already amounted to the same thing minus
        # zero-balance rows and real ancestor branches — see that
        # function's own comment in schema.sql ("matches
        # fn_trial_balance's rows, just without the always-show-every-
        # postable-leaf zero rows"). Gets Variance real chevrons and a
        # working zero-balances toggle, same as every other report, in
        # the one mode where that's actually meaningful: once a rollup
        # level below has genuinely collapsed several accounts' postings
        # into one pooled number, there's nothing finer left underneath
        # to expand or reveal.
        accounts = repo.dim_accounts(conn)
        baseline_by_id = repo.account_balances(conn, baseline, as_of_date) if baseline in codes else {}
        compare_by_id = repo.account_balances(conn, compare, as_of_date) if compare in codes else {}
        roots = build_account_tree(accounts, baseline_by_id, compare_by_id)
        grouped = []
        for t in ACCOUNT_TYPES:
            type_roots = [r for r in roots if r["account_type"] == t]
            rows = flatten_tree(type_roots, zeros)
            for r in rows:
                r["baseline_net"] = r["subtotal"]
                r["compare_net"] = r["compare_subtotal"]
                r["variance"] = variance_amount(r["baseline_net"], r["compare_net"], pct_of_base)
                r["pct_variance"] = pct_variance(r["baseline_net"], r["compare_net"], pct_of_base)
            if rows:
                sub_baseline = sum((rr["subtotal"] for rr in type_roots), Decimal(0))
                sub_compare = sum((rr["compare_subtotal"] for rr in type_roots), Decimal(0))
                grouped.append({
                    "type": t, "label": TYPE_LABELS[t], "rows": rows,
                    "sub_baseline": sub_baseline, "sub_compare": sub_compare,
                    "sub_variance": variance_amount(sub_baseline, sub_compare, pct_of_base),
                    "sub_pct_variance": pct_variance(sub_baseline, sub_compare, pct_of_base),
                })
        merged = [r for g in grouped for r in g["rows"]]
        # Roots only, not the full (branch + leaf) `merged` list — a
        # branch row's own baseline_net/compare_net already double-counts
        # its descendants, same reason Balance Sheet totals from
        # `asset_roots`/etc. rather than its own flattened display rows.
        total_baseline = sum((r["subtotal"] for r in roots), Decimal(0))
        total_compare = sum((r["compare_subtotal"] for r in roots), Decimal(0))
    else:
        # Rolled up to a chosen level — genuine SQL-side aggregation
        # across accounts posted at different native depths (e.g. a
        # Budget scenario posted straight to "Bank" reconciled against
        # Actual's separate Checking/Savings postings), so this stays on
        # fn_rollup_balance: no tree to walk, no zero rows to add — a
        # rolled-up row already represents whatever was pooled into it.
        baseline_rows = ({r["account_id"]: r for r in repo.rollup_balance(conn, baseline, level_depth, as_of_date)}
                          if baseline in codes else {})
        compare_rows = ({r["account_id"]: r for r in repo.rollup_balance(conn, compare, level_depth, as_of_date)}
                         if compare in codes else {})
        # fn_rollup_balance's own target account (whatever sits at the
        # chosen depth) is very often a summary account, not a postable
        # one — rolling up to "Top Level Accounts" pools everything under
        # e.g. "1000 Assets" itself, and nothing is ever posted directly
        # to a branch. Needed so a caller's entry_link (BACKLOG.md's
        # "make amounts clickable") doesn't link a pooled figure to an
        # exact-account-code Journal filter that can only ever come back
        # empty — same "not r.has_children" rule the native-depth branch
        # above already gets from a real tree, reused here via the one
        # signal rollup mode actually has for it.
        postable_by_id = repo.postable_flags(conn)

        merged = []
        for aid in set(baseline_rows) | set(compare_rows):
            b = baseline_rows.get(aid)
            c = compare_rows.get(aid)
            ref = b or c
            b_net = b["net"] if b else Decimal(0)
            c_net = c["net"] if c else Decimal(0)
            merged.append({
                "account_code": ref["account_code"], "account_name": ref["account_name"],
                "path": ref["path"], "sort_path": ref["sort_path"], "acct_type": ref["acct_type"],
                "baseline_net": b_net, "compare_net": c_net,
                "variance": variance_amount(b_net, c_net, pct_of_base),
                "pct_variance": pct_variance(b_net, c_net, pct_of_base),
                "has_children": not postable_by_id.get(aid, True),
            })

        grouped = []
        for t in ACCOUNT_TYPES:
            sub = sorted((r for r in merged if r["acct_type"] == t), key=lambda r: r["sort_path"])
            if sub:
                sub_baseline = sum((r["baseline_net"] for r in sub), Decimal(0))
                sub_compare = sum((r["compare_net"] for r in sub), Decimal(0))
                grouped.append({
                    "type": t, "label": TYPE_LABELS[t], "rows": sub,
                    "sub_baseline": sub_baseline, "sub_compare": sub_compare,
                    "sub_variance": variance_amount(sub_baseline, sub_compare, pct_of_base),
                    "sub_pct_variance": pct_variance(sub_baseline, sub_compare, pct_of_base),
                })
        total_baseline = sum((r["baseline_net"] for r in merged), Decimal(0))
        total_compare = sum((r["compare_net"] for r in merged), Decimal(0))

    return {
        "scens": scens, "compare": compare, "level_id": level_id,
        "merged": merged, "grouped": grouped, "rolled_up": level_depth is not None,
        "total_baseline": total_baseline, "total_compare": total_compare,
        "total_variance": variance_amount(total_baseline, total_compare, pct_of_base),
        "total_pct_variance": pct_variance(total_baseline, total_compare, pct_of_base),
    }
