"""Pure money arithmetic — variance/percentage math shared by every report
that compares two figures (Income Statement, Variance, the Budget grid).

Ported from `app/main.py`'s `_pct_variance`/`_variance_amount`/`_pct_of`/
`_divide` module-level helpers, with their docstrings kept close to
verbatim — they carry rationale that isn't obvious from the code (which
of the two figures plays "old" under each toggle state). Renamed without
the leading underscore since these are now a module's public surface
rather than file-private helpers.

Deliberately `Decimal`-typed rather than the legacy `float` mix (`app/
main.py`'s `_parse_lines` used `float(d)`/`float(c)` for debit/credit
input). `db/schema.sql` stores every amount as `NUMERIC`, which psycopg
already hands back as `Decimal` — the only place `float` ever entered
the picture was that one `float()` call on user input, a latent
imprecision risk with no upside. Fixed at the domain boundary rather than
carried forward; see REBUILD_STATUS.md's Phase 1.1 log entry.
"""
from decimal import Decimal

Money = Decimal | int | float


def normalize_zero(v: Money) -> Money:
    """A negative zero (`-1 * 0`) is the same value as `0` but %-style
    formatting renders it as the confusing "-0.00" — no reason to show a
    sign on a balance that's genuinely zero. Guards both `money()`'s own
    render path and any caller (like `accounts.build_account_tree`'s sign
    flip for credit-normal Income accounts) that flips a sign and might
    land on zero. Extracted here because the legacy code duplicated this
    exact guard in two places (`money()` and `_income_statement_groups`'
    inline `signed()`) with no shared helper."""
    return abs(v) if v == 0 else v


def pct_variance(base: Money, compare_val: Money, pct_of_base: bool = False) -> Money | None:
    """% variance between `base` (a report's own primary scenario figure
    — "Scenario" on Income Statement, "Baseline" on Variance, "Actual" on
    the Budget grid) and `compare_val` (whatever it's being measured
    against — "Compare to"/"Budgeted") — two conventions, user-toggleable
    per report via a "Flip variance direction" checkbox next to Hide
    zero balances (Income Statement, Variance, Budget Grid all share this
    one flag — see each route's own `pct_of_base` query param; the
    parameter name predates this docstring and stayed as-is since it's
    also a public, bookmarkable query string — only what it *does*
    changed here).

    Default (pct_of_base=False, unchecked): the standard percent-change
    reading, (new - old) / old, with `base` as the "new" figure and
    `compare_val` as the "old" one being measured against — (base -
    compare_val) / compare_val. "actual came in 12% ahead of budget."

    Checked (pct_of_base=True): the same reading with the two swapped —
    `compare_val` as "new", `base` as "old" — (compare_val - base) /
    base. "budget came in 12% ahead of actual."

    Both conventions divide by whichever figure is playing "old" in that
    state, not always the same one — so this takes the toggle as an
    explicit argument rather than being a caller-side negation. None
    (not 0%) when there's nothing to divide by."""
    if pct_of_base:
        if not base:
            return None
        return round((compare_val - base) / abs(base) * 100, 1)
    if not compare_val:
        return None
    return round((base - compare_val) / abs(compare_val) * 100, 1)


def variance_amount(base: Money, compare_val: Money, pct_of_base: bool = False) -> Money:
    """The plain-currency counterpart to pct_variance() above — same
    toggle, same two conventions, kept as its own function (not baked
    into pct_variance's return) since every call site needs both the
    dollar figure and the percentage rendered side by side, not one
    derived from the other. Default: base - compare_val (actual minus
    budget — positive when actual is ahead). Checked: compare_val - base
    (budget minus actual) — the numerator flips right along with which
    side of the % the toggle picks, so the sign of the dollar variance
    always agrees with whichever percentage is showing next to it."""
    return (compare_val - base) if pct_of_base else (base - compare_val)


def pct_of(amount: Money, total: Money) -> Money | None:
    """`amount` as a percentage of `total` — e.g. an Income Statement
    line's share of its own section total. None when `total` is zero
    (nothing to be a percentage of), matching pct_variance's None-not-0%
    convention above."""
    if not total:
        return None
    return round(amount / total * 100, 1)


def divide(v: Money | None, n: Money) -> Money | None:
    """`v / n`, propagating `None` rather than raising — used where `v`
    may already be `None` from an upstream computation (e.g. a scaled
    report cell with nothing to average) and the caller wants that to
    stay `None` rather than a `TypeError`."""
    return v / n if v is not None else None
