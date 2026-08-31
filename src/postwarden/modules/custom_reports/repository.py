"""Raw SQL access for the custom-reports module — one query family over
`v_fact_lines` (joined to `v_dim_account` only for the `account_level`
dimension), assembled from enum-keyed fragments.

The assembly below is the allowlist pattern `CUSTOM_REPORTS.md`'s
Architecture section specifies, stated once here so no individual
function has to restate it: every SQL fragment a query is composed from
is a developer-written constant keyed by a `Metric`/`Dimension` enum
member, or picked by an `if` on a typed filter — client input is never
interpolated into SQL, only ever bound as a query parameter. The
f-string composition over `_METRICS`/`_DIMENSIONS`/`_where()` is
therefore composition of trusted constants — the same trust story as
`modules/reports/repository.py`'s fully hand-written statements, just
factored, because seven dimensions × four metrics as 28 hand-written
queries would drift apart the way the pre-audit report pages did.

Same Core-not-ORM stance as `modules/reports/repository.py` (whose
docstring is the fullest statement of it): plain `text()` through the
shared `Connection`, plain dicts out, `Decimal` for every money value,
and nothing here decides anything beyond "here is what Postgres
returned" — validation and dispatch are `service.py`'s job. The
`_exists`/`account_level_depth` lookups are deliberate private forks of
the same one-liners other modules carry (the "deletable on its own"
rule — see `docs/ARCHITECTURE.md`), not candidates for sharing.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .enums import Dimension, Metric

# One SELECT aggregate per metric. `net_amount` flips credit-normal
# account types (liability/equity/income) so "spending" and "income"
# both read as positive in the obvious direction — the sign convention
# CUSTOM_REPORTS.md's metric table specifies, same normal_side logic
# v_dim_account derives. `entry_count` is distinct *entries*, not
# lines — "how many transactions matched," the number a person means.
_METRICS: dict[Metric, str] = {
    Metric.net_amount:
        "SUM(CASE WHEN f.account_type IN ('asset', 'expense') THEN f.amount ELSE -f.amount END)",
    Metric.debit_total: "SUM(f.debit)",
    Metric.credit_total: "SUM(f.credit)",
    Metric.entry_count: "COUNT(DISTINCT f.entry_id)",
}

# One (select, joins, group_by, order_by) shape per dimension. Every
# shape aliases its group key/display to `key`/`label` so the row shape
# stays uniform across dimensions and the frontend/table/export never
# branch on which dimension produced a row. Ordering is the dimension's
# own natural order (period ascending, account code, tag name) —
# chart-friendly reordering (pie slices by size) is presentation,
# left to the renderer.
#
# `account_level` reuses fn_rollup_balance's own sort_path-truncation
# expression inline (see that function in db/schema.sql) rather than
# calling it: the function's filters are fixed at (scenario, as_of),
# and a custom report needs the same rollup composed with *this*
# module's full filter set (date_from, tag, payee, account_type...).
# Same technique, same reporting-layer objects — just composable.
#
# `tag` unnests v_fact_lines.tags, so a line carrying two tags counts
# toward both groups — inherent to tags being overlapping labels
# (they're entry-grain and many-to-many; FORECAST.md §4A discusses why
# sums across tags don't partition). The ungrouped total (run_total)
# counts each line once, so a tag report's rows can legitimately sum to
# more than its total row.
_DIMENSIONS: dict[Dimension, dict[str, str]] = {
    Dimension.account: {
        "select": "f.account_id AS key, f.account_code || ' ' || f.account_name AS label",
        "joins": "",
        "group_by": "f.account_id, f.account_code, f.account_name",
        "order_by": "f.account_code",
    },
    Dimension.account_level: {
        "select": "tgt.id AS key, tgt.code || ' ' || tgt.name AS label",
        "joins": (
            "JOIN v_dim_account da ON da.id = f.account_id\n"
            "          JOIN v_dim_account tgt ON tgt.sort_path = array_to_string(\n"
            "              (string_to_array(da.sort_path, '.'))[1:LEAST(da.depth, :level_depth)], '.')"
        ),
        "group_by": "tgt.id, tgt.code, tgt.name, tgt.sort_path",
        "order_by": "tgt.sort_path",
    },
    Dimension.tag: {
        "select": "tg.tag AS key, tg.tag AS label",
        "joins": "CROSS JOIN LATERAL unnest(f.tags) AS tg(tag)",
        "group_by": "tg.tag",
        "order_by": "tg.tag",
    },
    Dimension.scenario: {
        "select": "f.scenario_code AS key, f.scenario_code AS label",
        "joins": "",
        "group_by": "f.scenario_code",
        "order_by": "f.scenario_code",
    },
    Dimension.month: {
        "select": "to_char(f.month, 'YYYY-MM') AS key, to_char(f.month, 'YYYY-MM') AS label",
        "joins": "",
        "group_by": "f.month",
        "order_by": "f.month",
    },
    Dimension.quarter: {
        "select": (
            "to_char(date_trunc('quarter', f.entry_date), 'YYYY-\"Q\"Q') AS key, "
            "to_char(date_trunc('quarter', f.entry_date), 'YYYY-\"Q\"Q') AS label"
        ),
        "joins": "",
        "group_by": "date_trunc('quarter', f.entry_date)",
        "order_by": "date_trunc('quarter', f.entry_date)",
    },
    Dimension.year: {
        "select": (
            "to_char(date_trunc('year', f.entry_date), 'YYYY') AS key, "
            "to_char(date_trunc('year', f.entry_date), 'YYYY') AS label"
        ),
        "joins": "",
        "group_by": "date_trunc('year', f.entry_date)",
        "order_by": "date_trunc('year', f.entry_date)",
    },
}


def _where(*, scenario: str | None, date_from: str | None, date_to: str | None,
           account_id: int | None, subtree: bool, tag_id: int | None,
           payee_id: int | None, account_type: str | None) -> tuple[str, dict]:
    """The shared WHERE for `run_report`/`run_total` — every clause a
    fixed string, every value a bound parameter, all AND-combined (no
    boolean tree — CUSTOM_REPORTS.md's Filters section)."""
    clauses: list[str] = []
    params: dict = {}
    if scenario:
        clauses.append("f.scenario_code = :scenario")
        params["scenario"] = scenario
    if date_from:
        clauses.append("f.entry_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        clauses.append("f.entry_date <= :date_to")
        params["date_to"] = date_to
    if account_id is not None:
        if subtree:
            # The account plus every descendant — walked from `accounts`
            # directly rather than string-matching v_dim_account paths.
            clauses.append(
                "f.account_id IN (\n"
                "    WITH RECURSIVE sub AS (\n"
                "        SELECT id FROM accounts WHERE id = :account_id\n"
                "        UNION ALL\n"
                "        SELECT a.id FROM accounts a JOIN sub ON a.parent_id = sub.id\n"
                "    ) SELECT id FROM sub)"
            )
        else:
            clauses.append("f.account_id = :account_id")
        params["account_id"] = account_id
    if tag_id is not None:
        # Entry-grain, matching how tags attach: every line of a tagged
        # entry is in scope, not just the "interesting" leg.
        clauses.append(
            "f.entry_id IN (SELECT entry_id FROM journal_entry_tags WHERE tag_id = :tag_id)")
        params["tag_id"] = tag_id
    if payee_id is not None:
        # v_fact_lines only carries the payee *name*; filter on the id
        # through journal_entries rather than trusting name round-trips.
        clauses.append(
            "f.entry_id IN (SELECT id FROM journal_entries WHERE payee_id = :payee_id)")
        params["payee_id"] = payee_id
    if account_type:
        # The space before `::` is load-bearing — a bind param directly
        # followed by a cast reads as neither to text()'s parser; see
        # budget_line_totals in modules/reports/repository.py for the
        # full story of that trap.
        clauses.append("f.account_type = :account_type ::account_type")
        params["account_type"] = account_type
    return " AND ".join(clauses) if clauses else "TRUE", params


def run_report(conn: Connection, metric: Metric, dimension: Dimension, *,
               level_depth: int | None = None, scenario: str | None = None,
               date_from: str | None = None, date_to: str | None = None,
               account_id: int | None = None, subtree: bool = False,
               tag_id: int | None = None, payee_id: int | None = None,
               account_type: str | None = None) -> list[dict]:
    """The grouped rows: `[{key, label, value}, ...]` in the dimension's
    natural order. `level_depth` is required by (and only used by) the
    `account_level` dimension — `service.py` resolves it from `level_id`
    before calling, same as Variance resolves its own."""
    spec = _DIMENSIONS[dimension]
    where, params = _where(scenario=scenario, date_from=date_from, date_to=date_to,
                           account_id=account_id, subtree=subtree, tag_id=tag_id,
                           payee_id=payee_id, account_type=account_type)
    if dimension is Dimension.account_level:
        params["level_depth"] = level_depth
    sql = (
        f"SELECT {spec['select']}, {_METRICS[metric]} AS value\n"
        f"  FROM v_fact_lines f\n"
        f"          {spec['joins']}\n"
        f" WHERE {where}\n"
        f" GROUP BY {spec['group_by']}\n"
        f" ORDER BY {spec['order_by']}"
    )
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def run_total(conn: Connection, metric: Metric, *, scenario: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              account_id: int | None = None, subtree: bool = False,
              tag_id: int | None = None, payee_id: int | None = None,
              account_type: str | None = None) -> Decimal | int:
    """The ungrouped total over the same filters — computed
    independently of the grouped rows rather than summed from them, so
    it stays honest for the two dimensions where rows overlap (`tag`:
    a two-tag line lands in both groups; `account`/`account_level` under
    `entry_count`: one entry touches several accounts). No dimension
    joins here — every metric reads `f.*` alone."""
    where, params = _where(scenario=scenario, date_from=date_from, date_to=date_to,
                           account_id=account_id, subtree=subtree, tag_id=tag_id,
                           payee_id=payee_id, account_type=account_type)
    sql = f"SELECT COALESCE({_METRICS[metric]}, 0) AS value FROM v_fact_lines f WHERE {where}"
    return conn.execute(text(sql), params).mappings().one()["value"]


# ---------------------------------------------------------------------------
# Validation lookups — service.py's "filter ids name real rows" checks.
# ---------------------------------------------------------------------------


def scenario_exists(conn: Connection, code: str) -> bool:
    return conn.execute(text("SELECT 1 FROM scenarios WHERE code = :code"),
                        {"code": code}).first() is not None


def account_exists(conn: Connection, account_id: int) -> bool:
    return conn.execute(text("SELECT 1 FROM accounts WHERE id = :id"),
                        {"id": account_id}).first() is not None


def tag_exists(conn: Connection, tag_id: int) -> bool:
    return conn.execute(text("SELECT 1 FROM tags WHERE id = :id"),
                        {"id": tag_id}).first() is not None


def payee_exists(conn: Connection, payee_id: int) -> bool:
    return conn.execute(text("SELECT 1 FROM payees WHERE id = :id"),
                        {"id": payee_id}).first() is not None


def account_level_depth(conn: Connection, level_id: int) -> int | None:
    """The `depth` a given `account_levels.id` sits at, or `None` if it
    doesn't exist — resolves the `level_id` query param into the depth
    the `account_level` dimension's rollup wants. Same private-fork
    one-liner `modules/reports/repository.py` carries for Variance."""
    row = conn.execute(text("SELECT depth FROM account_levels WHERE id = :level_id"),
                       {"level_id": level_id}).mappings().first()
    return row["depth"] if row else None
