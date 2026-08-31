"""Pure account-tree logic — rollup, flatten, and the P&L-net sign
correction shared by every report that walks the chart of accounts.

Ported from `app/main.py`'s module-level `_build_account_tree`/
`_flatten_tree`/`_pnl_net`/`_earnings_row`/`_accounts_with_gaps`,
docstrings kept close to verbatim. Callers pass plain dicts (what a
repository layer produces from a `v_dim_account` row and a
`fn_account_balances()` row) — this module never touches the database
itself, that's what makes it unit-testable in milliseconds.

`earnings_row` is the one deliberate divergence from that port: it's now
`earnings_rows` (plural), returning a real parent/children tree node
instead of a flat row — a rebuild-branch UX change, not a straight port,
see that function's own docstring and SPEC.md decision 10.

`income_statement_groups` joined this file in Phase 1.4 rather than
staying in `modules/reports/`: it's `_income_statement_groups` from
`app/main.py`, and despite living next to genuinely hard, DB-calling
report code there, the function itself never touches the database —
it's pure tree-signing/grouping on a `build_account_tree` result, the
same category as `flatten_tree` right above it. `modules/reports/
service.py` (the impure, DB-calling half of Income Statement) imports
it from here.
"""
from .money import normalize_zero, pct_variance, variance_amount

ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"]
TYPE_LABELS = {
    "asset": "Assets", "liability": "Liabilities", "equity": "Equity",
    "income": "Income", "expense": "Expenses",
}
# account_type -> the leading digit new codes in that type get minted
# under (see `_next_account_code` on the impure/repository side, which
# still has to hit the database to find the next free one).
ACCOUNT_TYPE_CODE_PREFIX = {
    "asset": "1", "liability": "2", "equity": "3", "income": "4", "expense": "5",
}


def pnl_net(accounts: list[dict], balances: dict) -> float:
    """Combined Income-minus-Expense across a {account_id: net} balance
    map, sign-corrected so a positive result means real earnings (credit
    side of Equity)."""
    income = sum(balances.get(a["id"], 0) for a in accounts if a["account_type"] == "income")
    expense = sum(balances.get(a["id"], 0) for a in accounts if a["account_type"] == "expense")
    return -income - expense


# Reserved ids for the synthetic "Retained Earnings" tree node (Trial
# Balance / Balance Sheet's own simulated-close split, SPEC.md decision
# 10) — fixed negative constants so they can never collide with a real
# `accounts.id` (Postgres serial, always positive) and stay stable
# across requests instead of depending on how many real accounts exist.
RETAINED_EARNINGS_ID = -1
CURRENT_YEAR_EARNINGS_ID = -2
PRIOR_YEAR_EARNINGS_ID = -3


def earnings_rows(current_year, prior_year, zeros: bool, depth: int = 2) -> list[dict]:
    """The unclosed-earnings figure as a real collapsible tree node —
    "Retained Earnings" (parent, rolled up total) with "Current Year
    Earnings (Unclosed)"/"Prior Year Earnings (Unclosed)" as its two leaf
    children — replacing what used to be two flat sibling rows with no
    `id`/`parent_id` at all (deliberately invisible to
    `useCollapsibleTree`, per that hook's own former comment). Giving
    this a real id is what makes it a genuine collapsible node instead:
    `useCollapsibleTree` only recognizes a parent/child relationship
    through a real numeric id pair, so a flat list could never have been
    made collapsible without this.

    Returns `[]` (no node at all, not just an empty subtree) when both
    figures are zero and `zeros` wasn't asked for — same all-or-nothing
    "is there anything here worth a Retained Earnings line at all" check
    Trial Balance always used, now shared by Balance Sheet's own version
    of this split too (see SPEC.md decision 10's Balance Sheet
    addendum) rather than each of the two lines independently
    disappearing at its own zero, which read oddly once they're a single
    parent/children unit instead of two unrelated rows.

    Every row carries both `debit_balance`/`credit_balance` (Trial
    Balance's own two-column layout, unflipped — a positive `amount`
    here already means "real earnings, credit side of Equity" per
    `pnl_net`'s own docstring) and `subtotal` (Balance Sheet's single
    signed Amount column) — `subtotal` is deliberately stored as
    `-amount`, the same "credit-normal, negative internally" convention
    every real Equity account's own `subtotal` already uses via
    `build_account_tree`'s `rollup()`, so Balance Sheet's existing
    per-section sign flip (`sign=-1` on the frontend, `-r["subtotal"]`
    in the CSV/XLSX exporters) turns it back into the correct positive-
    for-profit figure without any special-casing for these rows."""
    if not zeros and current_year == 0 and prior_year == 0:
        return []
    total = current_year + prior_year

    def row(id_: int, parent_id: int | None, name: str, amount, d: int, has_children: bool) -> dict:
        return {
            "id": id_, "parent_id": parent_id, "account_code": "", "account_name": name,
            "path": "", "depth": d, "has_children": has_children,
            "subtotal": -amount, "debit_balance": max(-amount, 0), "credit_balance": max(amount, 0),
        }

    return [
        row(RETAINED_EARNINGS_ID, None, "Retained Earnings", total, depth, True),
        row(CURRENT_YEAR_EARNINGS_ID, RETAINED_EARNINGS_ID, "Current Year Earnings (Unclosed)",
            current_year, depth + 1, False),
        row(PRIOR_YEAR_EARNINGS_ID, RETAINED_EARNINGS_ID, "Prior Year Earnings (Unclosed)",
            prior_year, depth + 1, False),
    ]


def build_account_tree(accounts: list[dict], balances_by_id: dict,
                        compare_by_id: dict | None = None) -> list[dict]:
    """The account forest (roots = accounts.parent_id IS NULL), each node
    carrying a "subtotal" that rolls up every descendant's own direct
    balance — the actual Trial Balance/Balance Sheet display figure.
    "net" stays each account's own direct postings only, same as
    fn_trial_balance always showed; "subtotal" is the new thing a summary
    account with subdivisions (e.g. "Current Assets"/"Long-term Assets"
    under "Assets") needed and never had.

    `compare_by_id` is optional — a second {account_id: net} map rolled
    up alongside the first into "compare_subtotal"/"compare_net", for
    Income Statement/Variance's own second-scenario column. A single
    tree this way drives both a plain report and a two-scenario
    comparison; callers that pass nothing get compare_subtotal fixed at
    0 for every node, which flatten_tree's zero-check treats as "no
    override" — the exact same hide-if-zero behavior as before this
    parameter existed."""
    compare_by_id = compare_by_id or {}
    nodes = {}
    for a in accounts:
        nodes[a["id"]] = {
            "id": a["id"], "parent_id": a["parent_id"], "account_code": a["code"],
            # parent_path (not path) — every caller renders this right next
            # to account_name, so it must exclude the account's own name or
            # the leaf reads twice (see v_dim_account's comment in schema.sql).
            "account_name": a["name"], "path": a["parent_path"], "account_type": a["account_type"],
            "depth": a["depth"], "net": balances_by_id.get(a["id"], 0),
            "compare_net": compare_by_id.get(a["id"], 0), "children": [],
        }
    roots = []
    for a in accounts:
        node = nodes[a["id"]]
        parent = nodes.get(a["parent_id"])
        (parent["children"] if parent else roots).append(node)

    def rollup(node):
        total, compare_total = node["net"], node["compare_net"]
        for c in node["children"]:
            b, cm = rollup(c)
            total += b
            compare_total += cm
        node["subtotal"] = total
        node["compare_subtotal"] = compare_total
        node["debit_balance"] = max(total, 0)
        node["credit_balance"] = max(-total, 0)
        return total, compare_total
    for r in roots:
        rollup(r)
    return roots


def flatten_tree(nodes: list[dict], zeros: bool) -> list[dict]:
    """Depth-first flatten for display, dropping any node (and its whole
    subtree) whose rolled-up subtotal is zero on *both* sides (own and
    compare — a row that only moved in one of the two scenarios is still
    activity worth showing), unless `zeros` — the same "hide accounts
    with no activity" rule Trial Balance always applied, just against the
    rollup instead of each account's own balance now. Adds has_children
    counting only what survives that filter, so a summary account left
    childless by it doesn't render a collapse arrow with nothing behind
    it."""
    out = []
    for node in nodes:
        if not zeros and node["subtotal"] == 0 and node.get("compare_subtotal", 0) == 0:
            continue
        kept_children = flatten_tree(node["children"], zeros)
        out.append({**node, "has_children": bool(kept_children)})
        out.extend(kept_children)
    return out


def income_statement_groups(roots: list[dict], t: str, flip: bool, zeros: bool,
                             pct_of_base: bool = False) -> list[dict]:
    """One group per top-level account of type `t` — multiple, for a
    second top-level expense account like "6000 Other" (see module
    comment). Each group's rows are that root's own flatten_tree()
    output, so the root itself opens the group as a normal (possibly
    collapsible) row rather than existing only as the header text above
    it, and any zero-balance root is dropped entirely unless `zeros` —
    same "no activity anywhere in this group" hiding the old flat merge
    gave for free by simply never creating the group. `flip` sign-
    corrects credit-normal Income rows (net < 0 for real income) so
    every amount from here on reads as a plain positive figure in its
    "normal" direction. `pct_of_base` — see pct_variance()'s own
    comment — is this scenario's own net (base_net/base_subtotal), not
    the compare scenario's."""
    sign = -1 if flip else 1

    def signed(x):
        return normalize_zero(sign * x)

    out = []
    for root in sorted((r for r in roots if r["account_type"] == t), key=lambda r: r["account_code"]):
        if not zeros and root["subtotal"] == 0 and root["compare_subtotal"] == 0:
            continue
        rows = flatten_tree([root], zeros)
        for r in rows:
            r["base_net"] = signed(r["subtotal"])
            r["compare_net"] = signed(r["compare_subtotal"])
            r["variance"] = variance_amount(r["base_net"], r["compare_net"], pct_of_base)
            r["pct_variance"] = pct_variance(r["base_net"], r["compare_net"], pct_of_base)
        out.append({
            "name": root["account_name"], "rows": rows,
            "base_subtotal": signed(root["subtotal"]), "compare_subtotal": signed(root["compare_subtotal"]),
        })
    for g in out:
        g["variance"] = variance_amount(g["base_subtotal"], g["compare_subtotal"], pct_of_base)
        g["pct_variance"] = pct_variance(g["base_subtotal"], g["compare_subtotal"], pct_of_base)
    return out


def accounts_with_gaps(accounts: list[dict]) -> list[dict]:
    """Interleaves a "gap" placeholder before every account row (and one
    trailing) so the Accounts screen can render an Actual Budget-style
    "+" for adding a category between any two adjacent rows, instead of
    only via the form at the bottom.

    Deliberately does NOT decide each gap's parent_id/account_type here —
    which two rows are visually adjacent around a given gap depends on
    which summary accounts are currently collapsed, and that's a client-
    side (localStorage) preference this function has no way to see. Each
    gap just needs to know which account row to track for visibility;
    the frontend computes the actual parent/type at "+"-click time from
    whichever rows are visible right then."""
    out = []
    prev = None
    for acct in accounts:
        out.append({"kind": "gap", "track_id": acct["id"]})
        out.append({"kind": "account", **acct})
        prev = acct
    out.append({"kind": "gap", "track_id": prev["id"] if prev else None})
    return out
