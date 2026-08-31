"""Raw SQL access for the imports module — both importers (plain CSV,
mapped/rules) land every entry they produce in Staging as one
`import_batches` row plus one `journal_entries` + `journal_lines` set per
group, exactly like `modules/staging/repository.py`'s own write helpers
land an approved entry in its target scenario. Ported from `app/main.py`'s
`_stage_import_groups`, plus the raw SQL inline in `_parse_csv_import` and
`import_page`.

**Forks `modules/entries/repository.py`'s `account_ids_by_code`/
`check_deferred_constraints` and `modules/staging/repository.py`'s
`actual_scenario_id`-shaped "look up the one Staging scenario" query,
rather than importing them.** Same test every prior module's own
docstring already applies (REBUILD.md decision 3): a module should be
deletable on its own, and importing across the vertical-slice boundary
fails that test in exactly the direction that matters here — deleting
`modules/entries/` or `modules/staging/` would break `modules/imports/`
even though staging a CSV row doesn't depend on either.

**No `scenarios`/`account_levels` picker payload in `recent_batches`**,
unlike legacy's `import_page` (which always passed the full target-
scenario picker list alongside the recent-batches table). Same "don't
reach into a module that doesn't exist yet" reasoning every prior write
module's own docstring already applies to `modules/reference/` (Phase
1.9) — `recent_batches` still joins `scenarios` directly for each row's
own `target_scenario_code` (a fact about that one batch, same as
`modules/staging/repository.py`'s own direct `scenarios` joins), just
without the separate "here's every scenario you could pick" list."""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection


def check_deferred_constraints(conn: Connection) -> None:
    """Identical in every respect to `modules.entries.repository`'s own
    function of the same name — see that module's docstring for the full
    explanation. Forked, not imported, for the reason this module's own
    docstring gives."""
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def account_ids_by_code(conn: Connection, codes: list[str]) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT code, id FROM accounts WHERE code = ANY(:codes)"), {"codes": codes}
    ).mappings()
    return {r["code"]: r["id"] for r in rows}


def staging_scenario_id(conn: Connection) -> int | None:
    """The one scenario `is_staging` names — ported from the inline
    `SELECT id FROM scenarios WHERE is_staging` in `_stage_import_groups`.
    `db/schema.sql`'s `uq_one_staging_scenario` caps this at one row,
    ever, same guarantee `modules/staging/repository.py`'s own lookups
    rely on."""
    row = conn.execute(text("SELECT id FROM scenarios WHERE is_staging")).mappings().first()
    return row["id"] if row else None


def upsert_payee(conn: Connection, name: str) -> int:
    """Ported from `_stage_import_groups`'s own `INSERT ... ON CONFLICT
    (name) DO UPDATE SET name = EXCLUDED.name RETURNING id` — the `DO
    UPDATE` is a no-op write, there only so `RETURNING id` fires on a
    conflict too (a plain `DO NOTHING` returns no row for an existing
    payee)."""
    row = conn.execute(text("""
        INSERT INTO payees (name) VALUES (:name)
        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """), {"name": name}).mappings().one()
    return row["id"]


def insert_import_batch(conn: Connection, *, filename: str, target_scenario_id: int,
                         imported_by_user_id: int | None, row_count: int) -> int:
    """One row per upload — `row_count` is `CHECK (row_count > 0)`
    (`db/schema.sql`), so this is only ever called once `service.py` has
    already confirmed at least one group parsed and validated cleanly."""
    row = conn.execute(text("""
        INSERT INTO import_batches (filename, target_scenario_id, imported_by_user_id, row_count)
        VALUES (:filename, :target_scenario_id, :imported_by_user_id, :row_count)
        RETURNING id
    """), {"filename": filename, "target_scenario_id": target_scenario_id,
           "imported_by_user_id": imported_by_user_id, "row_count": row_count}).mappings().one()
    return row["id"]


def insert_staged_entry(conn: Connection, *, scenario_id: int, entry_date, description: str,
                         reference: str | None, payee_id: int | None,
                         import_batch_id: int) -> str:
    """One staged `journal_entries` header — ported from `_stage_import_
    groups`'s own `INSERT`. Deliberately no `created_by_user_id`: legacy's
    own insert never sets it either (only the batch row's own `imported_
    by_user_id` records who ran the import), and an entry sitting in
    Staging isn't yet anyone's manual posting — see `modules.staging.
    service.approve_entry`, which is where `created_by_user_id` finally
    gets set, on the *approved* copy. `import_batch_id` is what satisfies
    `fn_staging_manual_entry_guard` (`db/schema.sql`) — a Staging-scenario
    insert needs exactly one of `scheduled_entry_id`/`import_batch_id`
    set, never neither."""
    row = conn.execute(text("""
        INSERT INTO journal_entries
               (scenario_id, entry_date, description, reference, payee_id, import_batch_id)
        VALUES (:scenario_id, :entry_date, :description, :reference, :payee_id, :import_batch_id)
        RETURNING id
    """), {"scenario_id": scenario_id, "entry_date": entry_date, "description": description,
           "reference": reference, "payee_id": payee_id,
           "import_batch_id": import_batch_id}).mappings().one()
    return row["id"]


def insert_line(conn: Connection, *, entry_id: str, line_no: int, account_id: int,
                 amount: Decimal, memo: str | None) -> None:
    """Identical shape to `modules.entries.repository.insert_line` —
    `amount` is the canonical signed figure (debit > 0, credit < 0)."""
    conn.execute(text("""
        INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
        VALUES (:entry_id, :line_no, :account_id, :amount, :memo)
    """), {"entry_id": entry_id, "line_no": line_no, "account_id": account_id,
           "amount": amount, "memo": memo})


def recent_batches(conn: Connection, limit: int) -> list[dict]:
    """The last `limit` uploads, newest first — ported from `import_page`'s
    own query, with one addition: `ib.id DESC` as a tiebreaker legacy's
    own `ORDER BY ib.created_at DESC` didn't have. `created_at` is `now()`,
    which returns the *transaction* start time in Postgres — identical for
    every row inserted by the same transaction, a real possibility here
    since `db.get_connection()` gives one request one transaction (unlike
    legacy's own per-route `tx()`, which never inserted more than one
    batch per commit anyway). Without the tiebreaker, two batches from the
    same request would sort arbitrarily instead of by insertion order.
    See this module's own docstring for why there's no separate
    scenario-picker payload alongside it."""
    rows = conn.execute(text("""
        SELECT ib.id, ib.filename, ib.row_count, ib.created_at,
               s.code AS target_scenario_code, u.username AS imported_by
          FROM import_batches ib
          JOIN scenarios s ON s.id = ib.target_scenario_id
          LEFT JOIN users u ON u.id = ib.imported_by_user_id
         ORDER BY ib.created_at DESC, ib.id DESC LIMIT :limit
    """), {"limit": limit}).mappings()
    return [dict(r) for r in rows]
