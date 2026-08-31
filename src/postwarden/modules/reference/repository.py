"""Raw SQL access for the reference module — Accounts, Account levels,
Scenarios, Payees, Tags. Every function takes a SQLAlchemy `Connection`
(from `db.get_connection()`) and returns plain dicts/lists/scalars, same
convention every prior module established.

**Five top-level resources in one module, not five modules.**
Accounts/account levels/scenarios/payees/tags are all pure reference
data — no report math, no journal-entry write path — and each one's own
CRUD is a few dozen lines. Splitting them into five separate `modules/`
packages would mean five near-empty `repository.py`/`service.py`/
`router.py` triples for what is, in every case, "list rows, insert a
row, toggle a boolean, maybe rename/delete." "A module should be
deletable on its own" still holds *within* this file — nothing here
imports from any other `modules/` package, and nothing outside this
module imports from it either; every module that needs one of these
lookups (`reports`, `budget`, `staging`, `imports`) forked its own small
copy instead of reaching in here.

**Five write routes `RETURNING`/rowcount-check and raise on an unknown
id:** `toggle_account`/`toggle_account_cashflow`, `toggle_lock`
(scenarios), and `rename_account_level`/`delete_account_level`. Every
sibling toggle/rename/delete route already raises `ValueError(f"...
#{id} not found")` on a miss, and a JSON API caller has more reason than
a form post did to get a real 400 back for "that id doesn't exist"
instead of a silent success — so these five match that behavior rather
than staying an asymmetric exception. `service.py` is where each of the
five actually raises.

`ACCOUNT_TYPES`/`SCENARIO_TYPES` live in `schemas.py` as `Literal` types
rather than plain lists — FastAPI/Pydantic validates a bad value into a
422 automatically, so there's no separate manual membership check
needed.
"""
from sqlalchemy import text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

# Seed.sql's own convention (1xxx assets, 2xxx liabilities, ...) isn't
# DB-enforced, just a habit — quick-created accounts follow it anyway so
# the chart stays legible without asking the user to think about codes.
ACCOUNT_TYPE_CODE_PREFIX = {
    "asset": "1", "liability": "2", "equity": "3", "income": "4", "expense": "5",
}


def list_accounts(conn: Connection, level_id: int | None = None) -> list[dict]:
    """Every account from `v_dim_account`, full hierarchy path and normal
    side included. `level_id` (when given) narrows to accounts sitting
    at that level's own depth."""
    if level_id is not None:
        row = conn.execute(
            text("SELECT depth FROM account_levels WHERE id = :level_id"), {"level_id": level_id}
        ).mappings().first()
        if row is None:
            return []
        rows = conn.execute(
            text("SELECT * FROM v_dim_account WHERE depth = :depth ORDER BY sort_path"),
            {"depth": row["depth"]},
        ).mappings()
    else:
        rows = conn.execute(text("SELECT * FROM v_dim_account ORDER BY sort_path")).mappings()
    return [dict(r) for r in rows]


def next_account_code(conn: Connection, account_type: str) -> str:
    """Ported from `_next_account_code` verbatim — the "+" quick-create
    picker generates a code rather than asking for one typed in."""
    prefix = ACCOUNT_TYPE_CODE_PREFIX[account_type]
    existing = {int(r["code"]) for r in conn.execute(
        text("SELECT code FROM accounts WHERE code LIKE :pattern"), {"pattern": prefix + "%"}
    ).mappings()}
    candidate = (max(existing) + 10) if existing else int(prefix + "000")
    while candidate in existing:
        candidate += 1
    return str(candidate)


def account_type_of(conn: Connection, account_id: int) -> str | None:
    """The parent's own `account_type` — `quick_create_account` derives a
    new leaf's type from its parent (when one is given) rather than
    trusting a caller-supplied type to already agree with it; the
    hierarchy-guard trigger would reject a mismatch anyway, but this lets
    the quick-create path never attempt one in the first place."""
    row = conn.execute(
        text("SELECT account_type FROM accounts WHERE id = :id"), {"id": account_id}
    ).mappings().first()
    return row["account_type"] if row else None


def insert_account(conn: Connection, *, code: str, name: str, account_type: str,
                    parent_id: int | None, is_postable: bool, is_cashflow: bool) -> dict:
    row = conn.execute(text("""
        INSERT INTO accounts (code, name, account_type, parent_id, is_postable, is_cashflow)
        VALUES (:code, :name, :account_type, :parent_id, :is_postable, :is_cashflow)
        RETURNING id, code, name
    """), {"code": code, "name": name, "account_type": account_type, "parent_id": parent_id,
           "is_postable": is_postable, "is_cashflow": is_cashflow}).mappings().one()
    return dict(row)


def toggle_account_active(conn: Connection, account_id: int) -> dict | None:
    row = conn.execute(text("""
        UPDATE accounts SET is_active = NOT is_active WHERE id = :id
        RETURNING id, code, name, is_active
    """), {"id": account_id}).mappings().first()
    return dict(row) if row else None


def toggle_account_cashflow(conn: Connection, account_id: int) -> dict | None:
    row = conn.execute(text("""
        UPDATE accounts SET is_cashflow = NOT is_cashflow WHERE id = :id
        RETURNING id, code, name, is_cashflow
    """), {"id": account_id}).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

def account_levels_all(conn: Connection) -> list[dict]:
    rows = conn.execute(text("""
        SELECT al.*,
               (SELECT COUNT(*) FROM scenarios s
                 WHERE s.base_level_id = al.id) AS scenario_count
          FROM account_levels al ORDER BY al.depth
    """)).mappings()
    return [dict(r) for r in rows]


def insert_account_level(conn: Connection, name: str, depth: int) -> dict:
    row = conn.execute(text("""
        INSERT INTO account_levels (name, depth) VALUES (:name, :depth)
        RETURNING id, name, depth
    """), {"name": name, "depth": depth}).mappings().one()
    return dict(row)


def rename_account_level(conn: Connection, level_id: int, name: str) -> int:
    result = conn.execute(
        text("UPDATE account_levels SET name = :name WHERE id = :id"),
        {"name": name, "id": level_id})
    return result.rowcount


def delete_account_level(conn: Connection, level_id: int) -> int:
    result = conn.execute(
        text("DELETE FROM account_levels WHERE id = :id"), {"id": level_id})
    return result.rowcount


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def scenarios_all(conn: Connection) -> list[dict]:
    rows = conn.execute(text("""
        SELECT s.*, al.name AS base_level_name,
               (SELECT COUNT(*) FROM journal_entries e
                 WHERE e.scenario_id = s.id) AS entry_count
          FROM scenarios s
          LEFT JOIN account_levels al ON al.id = s.base_level_id
         ORDER BY s.scenario_type, s.code
    """)).mappings()
    return [dict(r) for r in rows]


def insert_scenario(conn: Connection, *, code: str, name: str, scenario_type: str,
                     enforce_balance: bool, income_statement_only: bool,
                     base_level_id: int | None, notes: str | None) -> dict:
    row = conn.execute(text("""
        INSERT INTO scenarios
               (code, name, scenario_type, enforce_balance,
                income_statement_only, base_level_id, notes)
        VALUES (:code, :name, :scenario_type, :enforce_balance,
                :income_statement_only, :base_level_id, :notes)
        RETURNING id, code, name
    """), {"code": code, "name": name, "scenario_type": scenario_type,
           "enforce_balance": enforce_balance, "income_statement_only": income_statement_only,
           "base_level_id": base_level_id, "notes": notes}).mappings().one()
    return dict(row)


def toggle_scenario_lock(conn: Connection, scenario_id: int) -> dict | None:
    row = conn.execute(text("""
        UPDATE scenarios SET is_locked = NOT is_locked WHERE id = :id
        RETURNING id, code, is_locked
    """), {"id": scenario_id}).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

def payees_all(conn: Connection) -> list[dict]:
    rows = conn.execute(text("""
        SELECT p.*, (SELECT COUNT(*) FROM journal_entries e
                      WHERE e.payee_id = p.id) AS entry_count
          FROM payees p ORDER BY p.name
    """)).mappings()
    return [dict(r) for r in rows]


def insert_payee(conn: Connection, name: str) -> dict:
    row = conn.execute(text("""
        INSERT INTO payees (name) VALUES (:name) RETURNING id, name
    """), {"name": name}).mappings().one()
    return dict(row)


def quick_create_payee(conn: Connection, name: str) -> dict:
    """`ON CONFLICT DO UPDATE` (a no-op update), not `DO NOTHING` — the
    standard trick to get `RETURNING` even when the name already exists.
    It also quietly reactivates an archived payee, which is what typing
    its name here signals — ported from `quick_create_payee` verbatim."""
    row = conn.execute(text("""
        INSERT INTO payees (name) VALUES (:name)
        ON CONFLICT (name) DO UPDATE SET is_active = TRUE
        RETURNING id, name
    """), {"name": name}).mappings().one()
    return dict(row)


def toggle_payee_active(conn: Connection, payee_id: int) -> dict | None:
    row = conn.execute(text("""
        UPDATE payees SET is_active = NOT is_active WHERE id = :id
        RETURNING id, name, is_active
    """), {"id": payee_id}).mappings().first()
    return dict(row) if row else None


def rename_payee(conn: Connection, payee_id: int, name: str) -> int:
    result = conn.execute(
        text("UPDATE payees SET name = :name WHERE id = :id"), {"name": name, "id": payee_id})
    return result.rowcount


def delete_payee(conn: Connection, payee_id: int) -> str | None:
    """Every FK onto `payees(id)` is `ON DELETE SET NULL` — safe by
    construction: any entry that used this payee just goes back to
    having none."""
    row = conn.execute(
        text("DELETE FROM payees WHERE id = :id RETURNING name"), {"id": payee_id}
    ).mappings().first()
    return row["name"] if row else None


def merge_payees(conn: Connection, survivor_id: int, other_ids: list[int], target_name: str) -> int | None:
    """Repoints every FK onto the merged-away ids, deletes them, then
    renames the survivor. Deleting the others *before* the rename
    matters: if `target_name` equals one of the about-to-be-deleted
    payees' own current name, renaming the survivor first would collide
    with `payees.name`'s UNIQUE constraint. Returns the number of
    `journal_entries` rows repointed (`None` if `survivor_id` doesn't
    exist) — `scheduled_entries`/`entry_templates` are repointed too but
    not counted in that figure.

    **Checks `survivor_id` exists up front.** Left unchecked, a bad
    survivor id would still fail, just later and less predictably: every
    `payee_id` column the repoint `UPDATE`s touch is a real FK onto
    `payees(id)`, so pointing one at an id that doesn't exist would raise
    a raw `ForeignKeyViolation` the moment any of the merged-away payees
    actually had an entry. Same "resolve it up front instead of relying
    on a constraint violation" fix `modules.imports.service.
    stage_import_groups` makes for unmapped account codes."""
    if conn.execute(text("SELECT 1 FROM payees WHERE id = :id"), {"id": survivor_id}).first() is None:
        return None
    result = conn.execute(
        text("UPDATE journal_entries SET payee_id = :survivor WHERE payee_id = ANY(:others)"),
        {"survivor": survivor_id, "others": other_ids})
    affected = result.rowcount
    conn.execute(
        text("UPDATE scheduled_entries SET payee_id = :survivor WHERE payee_id = ANY(:others)"),
        {"survivor": survivor_id, "others": other_ids})
    conn.execute(
        text("UPDATE entry_templates SET payee_id = :survivor WHERE payee_id = ANY(:others)"),
        {"survivor": survivor_id, "others": other_ids})
    conn.execute(text("DELETE FROM payees WHERE id = ANY(:others)"), {"others": other_ids})
    result = conn.execute(
        text("UPDATE payees SET name = :name WHERE id = :id"),
        {"name": target_name, "id": survivor_id})
    if result.rowcount == 0:
        return None
    return affected


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def tags_all(conn: Connection) -> list[dict]:
    rows = conn.execute(text("""
        SELECT t.*, (SELECT COUNT(*) FROM journal_entry_tags jet
                      WHERE jet.tag_id = t.id) AS entry_count
          FROM tags t ORDER BY t.name
    """)).mappings()
    return [dict(r) for r in rows]


def insert_tag(conn: Connection, name: str) -> dict:
    row = conn.execute(text("""
        INSERT INTO tags (name) VALUES (:name) RETURNING id, name
    """), {"name": name}).mappings().one()
    return dict(row)


def toggle_tag_active(conn: Connection, tag_id: int) -> dict | None:
    row = conn.execute(text("""
        UPDATE tags SET is_active = NOT is_active WHERE id = :id
        RETURNING id, name, is_active
    """), {"id": tag_id}).mappings().first()
    return dict(row) if row else None


def rename_tag(conn: Connection, tag_id: int, name: str) -> int:
    result = conn.execute(
        text("UPDATE tags SET name = :name WHERE id = :id"), {"name": name, "id": tag_id})
    return result.rowcount


def delete_tag(conn: Connection, tag_id: int) -> str | None:
    """`journal_entry_tags`/`scheduled_entry_tags`/`entry_template_tags`
    are all `ON DELETE CASCADE` (unlike payees' `SET NULL`) — deleting a
    tag just drops it from whatever it was on."""
    row = conn.execute(
        text("DELETE FROM tags WHERE id = :id RETURNING name"), {"id": tag_id}
    ).mappings().first()
    return row["name"] if row else None


def merge_tags(conn: Connection, survivor_id: int, other_ids: list[int], target_name: str) -> int | None:
    """Unlike payees, a tag's associations are many-to-many across three
    junction tables — each gets an "insert the survivor's own association
    wherever a merged-away tag had one, ON CONFLICT DO NOTHING" pass
    before the old tag rows are deleted, since a plain `UPDATE ... SET
    tag_id` could collide with an (entry_id, tag_id) pair that already
    exists (something tagged with *both* the survivor and a tag being
    folded into it) and violate the junction table's own primary key.
    Returns distinct `journal_entries` affected (`None` if `survivor_id`
    doesn't exist) — `scheduled_entries`/`entry_templates` carrying a
    merged tag aren't reflected in that count either.

    **Checks `survivor_id` exists up front** — same fix, same reason, as
    `merge_payees` above: left unchecked, a bad survivor id would surface
    as a raw `ForeignKeyViolation` on the junction-table `INSERT` the
    moment any merged-away tag actually had an association."""
    if conn.execute(text("SELECT 1 FROM tags WHERE id = :id"), {"id": survivor_id}).first() is None:
        return None
    affected = conn.execute(
        text("SELECT COUNT(DISTINCT entry_id) AS n FROM journal_entry_tags WHERE tag_id = ANY(:others)"),
        {"others": other_ids}).mappings().one()["n"]
    for table, id_col in (("journal_entry_tags", "entry_id"),
                           ("scheduled_entry_tags", "scheduled_entry_id"),
                           ("entry_template_tags", "template_id")):
        conn.execute(text(f"""
            INSERT INTO {table} ({id_col}, tag_id)
            SELECT {id_col}, :survivor FROM {table} WHERE tag_id = ANY(:others)
            ON CONFLICT DO NOTHING
        """), {"survivor": survivor_id, "others": other_ids})
    conn.execute(text("DELETE FROM tags WHERE id = ANY(:others)"), {"others": other_ids})
    result = conn.execute(
        text("UPDATE tags SET name = :name WHERE id = :id"),
        {"name": target_name, "id": survivor_id})
    if result.rowcount == 0:
        return None
    return affected
