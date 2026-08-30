"""Budget grid assembly and the single-cell save — ported from
`app/main.py`'s `_budget_rows`/`save_budget_cell`, comments and docstrings
kept close to verbatim per `REBUILD.md` §6's own instruction for a hard
report function. Every function here takes a SQLAlchemy `Connection`
(from `db.get_connection()`, same as every other module) and reads
through `repository.py` — never raw SQL of its own.

**One real consolidation, not just a rename.** Legacy's `_budget_rows` has
its own local `flatten(nodes)` helper that walks the merged tree with no
zero-filtering at all — every account shows on the grid, budgeted or not,
because you need to see a row to type a number into it. That turns out to
be exactly what `domain.accounts.flatten_tree(nodes, zeros=True)` already
does: `zeros=True` is precisely "never drop a zero-subtotal branch," and
with nothing ever dropped, `has_children` collapses to the same plain
`bool(node["children"])` legacy's own local version computed by hand. So
this module calls the existing domain function with `zeros=True` instead
of carrying a second, near-identical flatten implementation — one more
instance of the "legacy duplicated this exact logic with no shared
helper" pattern `domain/money.py`'s `normalize_zero` docstring already
flagged for the sign-flip zero guard (also reused here, for the same
reason: `merge()`'s own `signed()` closure needs it, same as `income_
statement_groups`'s did).
"""
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.engine import Connection

from ...domain.accounts import TYPE_LABELS, build_account_tree, flatten_tree
from ...domain.money import normalize_zero, pct_variance, variance_amount
from ...domain.periods import shift_month
from . import repository as repo

# ---------------------------------------------------------------------------
# Budget grid
# ---------------------------------------------------------------------------


def budget_grid(conn: Connection, scenario: str, month: str, pct_of_base: bool = False) -> dict:
    """Ported from `app/main.py`'s `_budget_rows`, unchanged in shape: one
    month at a time, Actual (this month's real postings in ACTUAL),
    Variance against Budgeted (both sharing the money-in-between reading
    order every other two-scenario report uses), and Budgeted itself
    (editable) last — income/expense accounts only, no journal entries in
    sight for the scenario itself since an income-statement-only scenario
    never takes one (`fn_income_statement_only_guard`). Reuses `build_
    account_tree` twice — once over `budget_lines`, once over ACTUAL's own
    postings for the same month — and merges the two node-for-node rather
    than inventing a second rollup function, since both sides share the
    exact same account tree shape.

    `month` must already be a valid `YYYY-MM-01` string (the router's own
    job, same as legacy's `budget_page` route: normalizing a stale/hand-
    typed month before ever calling this). Returns the zero-figure stub
    legacy's route inlined itself when `scenario` doesn't resolve to a
    real income-statement-only scenario — folded in here instead, so
    every caller (including a future CSV export, `export/`, Phase 1.12)
    gets the same fallback with no risk of drifting from it."""
    month_start = date.fromisoformat(month)
    month_end = date(month_start.year, month_start.month,
                      calendar.monthrange(month_start.year, month_start.month)[1])
    scen = repo.income_statement_only_scenario(conn, scenario) if scenario else None
    if not scen:
        return {"grouped": [], "net_budgeted": 0, "net_actual": 0, "net_variance": 0,
                "net_pct_variance": None, "month_start": month_start.isoformat(),
                "month_end": month_end.isoformat()}

    accounts = repo.dim_accounts(conn)
    budgeted_by_id = repo.budget_line_amounts(conn, scen["id"], month_start)
    actual_by_id = repo.account_balances(conn, "ACTUAL", month_end.isoformat(), month_start.isoformat())

    # BACKLOG.md's own chevron menu ("Set to ACTUAL value of last month",
    # "Set to 3 month average of ACTUAL", ...) needs last month's own
    # figures and a 3-calendar-month average, for both ACTUAL and whatever
    # scenario is currently open — computed once here, per account, rather
    # than a second round trip when a chevron is clicked. Average is a
    # plain sum-over-3 (zero for a quiet month, not excluded from the
    # denominator), same convention Income Statement Split's own Average
    # column already uses (SPEC.md decision 19's addendum).
    prev_month_start = date.fromisoformat(shift_month(month, -1))
    prev_month_end = date(prev_month_start.year, prev_month_start.month,
                           calendar.monthrange(prev_month_start.year, prev_month_start.month)[1])
    three_month_start = date.fromisoformat(shift_month(month, -3))

    prev_actual_by_id = repo.account_balances(
        conn, "ACTUAL", prev_month_end.isoformat(), prev_month_start.isoformat())
    avg3_actual_raw = repo.account_balances(
        conn, "ACTUAL", prev_month_end.isoformat(), three_month_start.isoformat())
    avg3_actual_by_id = {account_id: net / 3 for account_id, net in avg3_actual_raw.items()}
    prev_budget_by_id = repo.budget_line_amounts(conn, scen["id"], prev_month_start)
    avg3_budget_by_id = repo.budget_line_avg3(conn, scen["id"], three_month_start, month_start)

    budget_roots = build_account_tree(accounts, budgeted_by_id)
    actual_by_node_id = {}

    def index(nodes):
        for n in nodes:
            actual_by_node_id[n["id"]] = n
            index(n["children"])
    index(build_account_tree(accounts, actual_by_id))

    def merge(nodes):
        out = []
        for n in nodes:
            # journal amounts are debit-positive, so an income account's
            # actual net comes out negative; budget_lines.amount is a
            # plain target with no sign to juggle — flip actual's sign for
            # income so both columns read as a positive "how much", same
            # as Income Statement already does for income rows.
            sign = -1 if n["account_type"] == "income" else 1

            def signed(x, sign=sign):
                return normalize_zero(sign * x)
            budgeted = n["subtotal"]
            actual = signed(actual_by_node_id[n["id"]]["subtotal"])
            out.append({
                **n, "budgeted": budgeted, "actual": actual,
                "variance": variance_amount(actual, budgeted, pct_of_base),
                "pct_variance": pct_variance(actual, budgeted, pct_of_base),
                # Only meaningful on a leaf's own editable cell — computed
                # uniformly here regardless, since a summary node's copy is
                # simply never rendered (the frontend's own has_children
                # branch), and branching here would just be extra code for
                # no benefit.
                "quickfill": {
                    "last_actual": signed(prev_actual_by_id.get(n["id"], 0)),
                    "last_scenario": prev_budget_by_id.get(n["id"], 0),
                    "avg3_actual": signed(avg3_actual_by_id.get(n["id"], 0)),
                    "avg3_scenario": avg3_budget_by_id.get(n["id"], 0),
                },
                "children": merge(n["children"]),
            })
        return out
    merged_roots = merge(budget_roots)

    grouped = []
    for t in ("income", "expense"):
        type_roots = [n for n in merged_roots if n["account_type"] == t]
        sub_budgeted = sum(n["budgeted"] for n in type_roots)
        sub_actual = sum(n["actual"] for n in type_roots)
        grouped.append({
            "type": t, "label": TYPE_LABELS[t],
            # zeros=True: every account shows, budgeted or not — see this
            # module's own docstring for why this is domain.accounts.
            # flatten_tree, not a second bespoke flatten.
            "rows": flatten_tree(type_roots, zeros=True),
            "sub_budgeted": sub_budgeted, "sub_actual": sub_actual,
            "sub_variance": variance_amount(sub_actual, sub_budgeted, pct_of_base),
            "sub_pct_variance": pct_variance(sub_actual, sub_budgeted, pct_of_base),
        })
    grouped_by_type = {g["type"]: g for g in grouped}
    net_budgeted = grouped_by_type["income"]["sub_budgeted"] - grouped_by_type["expense"]["sub_budgeted"]
    net_actual = grouped_by_type["income"]["sub_actual"] - grouped_by_type["expense"]["sub_actual"]

    return {
        "grouped": grouped, "month_start": month_start.isoformat(), "month_end": month_end.isoformat(),
        "net_budgeted": net_budgeted, "net_actual": net_actual,
        "net_variance": variance_amount(net_actual, net_budgeted, pct_of_base),
        "net_pct_variance": pct_variance(net_actual, net_budgeted, pct_of_base),
    }


# ---------------------------------------------------------------------------
# Single-cell save
# ---------------------------------------------------------------------------


def save_budget_cell(conn: Connection, *, scenario_id: int, account_code: str, period_month: date,
                      amount_raw: str) -> Decimal:
    """Ported from `app/main.py`'s `save_budget_cell` (minus `require_
    csrf`/session concerns — `modules/auth/`, Phase 1.11, same documented
    gap `modules/entries/router.py`'s own docstring already carries).
    `amount_raw` stays a plain string in the request body, parsed to
    `Decimal` here rather than a Pydantic numeric field — same reasoning
    `modules.entries.schemas.EntryLineIn` gives for `debit`/`credit`: one
    parsing question, answered once. Unlike legacy's own `round(float(...),
    2)`, this parses straight to `Decimal` — the same fix `domain.entry.
    parse_lines` already applied to debit/credit input, for the same
    reason (`NUMERIC(18,2)` all the way down; `float` was only ever a
    latent-imprecision risk with no upside). Raises `ValueError` for a
    non-numeric amount or an unknown account code — the router's job to
    turn into a 400; `fn_budget_line_guard`'s own rejections (wrong
    scenario type, locked scenario, non-income/expense or non-postable
    account) surface as `sqlalchemy.exc.SQLAlchemyError` instead, same as
    every other write module's trigger-backed validation."""
    try:
        amount = Decimal(amount_raw).quantize(Decimal("0.01")) if amount_raw else Decimal("0.00")
    except InvalidOperation:
        raise ValueError(f"{amount_raw!r} isn't a number")
    account_id = repo.account_id_by_code(conn, account_code)
    if account_id is None:
        raise ValueError(f"Unknown account code: {account_code}")
    repo.upsert_budget_cell(conn, scenario_id, account_id, period_month, amount)
    return amount
