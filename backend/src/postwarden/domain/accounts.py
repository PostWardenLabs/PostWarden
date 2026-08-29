"""Pure account-tree logic — rollup, flatten, and the P&L-net sign
correction shared by every report that walks the chart of accounts.

Ported from `app/main.py`'s module-level `_build_account_tree`/
`_flatten_tree`/`_pnl_net`/`_earnings_row`/`_accounts_with_gaps`,
docstrings kept close to verbatim. Callers pass plain dicts (what a
repository layer produces from a `v_dim_account` row and a
`fn_account_balances()` row) — this module never touches the database
itself, that's what makes it unit-testable in milliseconds.
"""
from .money import normalize_zero

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


def earnings_row(name: str, amount, depth: int = 2) -> dict:
    """A synthetic Trial Balance row for an unclosed-earnings figure
    (Current/Prior Year Earnings) that has no backing `accounts` row —
    same shape a real flattened tree row has, so it renders identically."""
    return {"account_code": "", "account_name": name, "path": "", "depth": depth,
            "has_children": False, "debit_balance": max(-amount, 0), "credit_balance": max(amount, 0)}


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
