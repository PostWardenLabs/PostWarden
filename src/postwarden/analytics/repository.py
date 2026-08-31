"""Raw SQL access for the `/api/*` JSON mirror — every function here reads
one of the star-schema views `db/schema.sql` grants to `postwarden_bi`
(`v_dim_account`, `v_fact_lines`, `v_monthly_activity`) or the
`fn_trial_balance` set-returning function, plus one plain table read
(`scenarios`) for `/api/scenarios`' own richer shape.

Every function here is its own fork of a query a sibling module already
has a version of, not an import — the same REBUILD.md decision 3
"deletable on its own" test every prior module already applies. This
one cuts in both directions at once: `modules/reports/repository.py`'s
`dim_accounts` filters to `WHERE is_active` (a report never shows an
archived account) and `modules/reference/repository.py`'s
`scenarios_all` is reference's own CRUD-page shape — this module's
versions are verbatim ports of `app/main.py`'s own `api_accounts`/
`api_scenarios`, which predate either of those and were never actually
identical to begin with (`api_accounts` has no `is_active` filter at
all — the JSON mirror always showed every account, archived or not).
Deleting `modules/reports/` or `modules/reference/` should never take
the `/api/*` contract down with it, and vice versa.

Every function takes `conn` as its first argument and returns plain
dicts/lists — `Decimal` for every money value, unchanged by `service.py`
(there is no report-shaped assembly to do here; the JSON mirror hands
back exactly what the view/function already computed, same as legacy).
"""
from sqlalchemy import text
from sqlalchemy.engine import Connection


def trial_balance(conn: Connection, scenario: str, as_of: str | None) -> list[dict]:
    """`fn_trial_balance(scenario, as_of)`, verbatim — every active
    account's own trial-balance row, `NULL` `as_of` meaning "through
    today" (the function's own default, per its `schema.sql` docstring).
    No `p_from` — legacy's `api_trial_balance` never exposed one, and this
    module ports what `/api/*` actually did, not `fn_trial_balance`'s
    full capability."""
    rows = conn.execute(
        text("SELECT * FROM fn_trial_balance(:scenario, :as_of)"),
        {"scenario": scenario, "as_of": as_of},
    ).mappings()
    return [dict(r) for r in rows]


def accounts(conn: Connection) -> list[dict]:
    """Every account, active or not — `api_accounts`'s own `SELECT * FROM
    v_dim_account ORDER BY sort_path`, no `WHERE is_active` at all. A
    verbatim port, not an oversight: unlike every report/picker in this
    app, the JSON mirror is meant to hand back the whole dimension table
    for a BI tool building its own model, where an archived account is
    still a real row with real history, not noise to filter out."""
    rows = conn.execute(text("SELECT * FROM v_dim_account ORDER BY sort_path")).mappings()
    return [dict(r) for r in rows]


def scenarios(conn: Connection) -> list[dict]:
    """Every scenario plus its own `base_level_name`/`entry_count` —
    `api_scenarios`'s own `scenarios_all()` call, forked verbatim rather
    than imported from `modules/reference/repository.py`'s identically-
    shaped `scenarios_all` (see this module's own docstring)."""
    rows = conn.execute(text("""
        SELECT s.*, al.name AS base_level_name,
               (SELECT COUNT(*) FROM journal_entries e
                 WHERE e.scenario_id = s.id) AS entry_count
          FROM scenarios s
          LEFT JOIN account_levels al ON al.id = s.base_level_id
         ORDER BY s.scenario_type, s.code
    """)).mappings()
    return [dict(r) for r in rows]


def fact_lines(conn: Connection, scenario: str | None, date_from: str | None,
               date_to: str | None) -> list[dict]:
    """Up to 1000 `v_fact_lines` rows, newest first — `api_entries`'s own
    query, same optional `scenario_code`/`entry_date` filters and the
    same `ORDER BY entry_date DESC, seq DESC, line_id` tiebreak (`seq`,
    not `entry_id`: entry ids are random codes, not sequential — see
    `v_fact_lines`'s own comment in `schema.sql` for why `created_at`
    alone isn't enough either, since one transaction can insert several
    entries sharing a single `now()`). The 1000-row cap is legacy's own
    `LIMIT`, ported as-is — this is a JSON mirror for scripts, not a
    paginated browser."""
    where, params = ["TRUE"], {}
    if scenario:
        where.append("scenario_code = :scenario")
        params["scenario"] = scenario
    if date_from:
        where.append("entry_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("entry_date <= :date_to")
        params["date_to"] = date_to
    rows = conn.execute(text(
        f"SELECT * FROM v_fact_lines WHERE {' AND '.join(where)} "
        "ORDER BY entry_date DESC, seq DESC, line_id LIMIT 1000"
    ), params).mappings()
    return [dict(r) for r in rows]


def monthly_activity(conn: Connection, scenario: str | None) -> list[dict]:
    """Every `v_monthly_activity` row, optionally narrowed to one
    scenario — `api_monthly`'s own query, unchanged."""
    if scenario:
        rows = conn.execute(text(
            "SELECT * FROM v_monthly_activity WHERE scenario_code = :scenario "
            "ORDER BY month, account_code"
        ), {"scenario": scenario}).mappings()
    else:
        rows = conn.execute(text(
            "SELECT * FROM v_monthly_activity ORDER BY month, account_code"
        )).mappings()
    return [dict(r) for r in rows]
