"""Raw SQL access for the scheduling module — two lifecycles that share
one file because both are "scaffolding for a future journal entry," not
because they're the same thing:

- **Scheduled entries** (`scheduled_entries` + `scheduled_entry_lines`,
  SPEC.md decision 9) are a template plus a recurrence rule. A due
  occurrence never posts straight to its own `target_scenario_id` — it
  first becomes a real, pending `journal_entries` row in Staging
  (`materialize_due_schedules`, `service.py`), and only a human
  approving it from `modules/staging/` turns that into a second, real
  posting. This module owns the schedule and the materializing;
  `modules/staging/` already owns everything from "pending in Staging"
  onward.
- **Entry templates** (`entry_templates` + `entry_template_lines`) never
  post anywhere on their own — they're reusable scaffolding for the New
  entry form's "Load template" picker, the same as typing a line by
  hand. No recurrence, no materializing, no Staging involvement at all.

Same conventions every prior module established: every function takes a
SQLAlchemy `Connection` (from `db.get_connection()`) and returns plain
dicts/lists/scalars, `Decimal` for every money value, never `float`.

**Forks `modules/entries/repository.py`'s `account_ids_by_code`/
`insert_line`/`check_deferred_constraints` and `modules/imports/
repository.py`'s `staging_scenario_id`-shaped lookup, rather than
importing them** — the same "a module should be deletable on its own"
test every prior write module's own docstring already applies: deleting
`modules/entries/`, `modules/staging/`, or
`modules/imports/` should never break `modules/scheduling/`, even
though materializing a due schedule's occurrence doesn't conceptually
depend on any of them. `insert_staged_occurrence` is this module's own
version of `modules.imports.repository.insert_staged_entry`, setting
`scheduled_entry_id` instead of `import_batch_id` — `journal_entries`'
`fn_staging_manual_entry_guard` needs exactly one of the two set, never
neither, same guard both producers satisfy.

**`check_deferred_constraints` is needed here for the same real reason
`modules/entries/repository.py`'s own docstring gives, not a
theoretical one.** `materialize_due_schedules` inserts a full
`journal_entries` + `journal_lines` set into Staging, which is a real,
`enforce_balance = TRUE` scenario like any other (SPEC.md decision 9) —
`trg_lines_balanced`/`trg_entry_has_lines` apply to it exactly the same
way they do to a manually-posted entry, and are just as `DEFERRABLE
INITIALLY DEFERRED`. `db.get_connection()`'s one-transaction-per-request
design has no per-schedule commit point of its own to trigger the
deferred check independently, so `service.materialize_due_schedules`
calls this — and wraps each schedule in its own `Connection.
begin_nested()` SAVEPOINT, the same `reverse_entries_bulk` technique
`modules/entries/service.py` already uses — so one schedule's bad data
can't silently corrupt or block the next one's insert.

**Two write routes check-and-raise on an unknown id instead of silently
no-op'ing: `toggle_schedule` and `delete_template`.** This is the same
class of oversight `modules/reference/repository.py`'s own docstring
already found and fixed for `toggle_account`/`toggle_account_cashflow`/
`toggle_lock`/
`rename_account_level`/`delete_account_level` — nothing in `SPEC.md`
singles out schedules or templates as special here, and
every *other* toggle/rename/delete route across the app already checks.
`toggle_schedule_active` (below) `RETURNING`s the updated row, `None` on
a miss, same idiom `modules/reference/repository.py` settled on;
`delete_template`'s rowcount is what `service.delete_template` checks.
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection


def check_deferred_constraints(conn: Connection) -> None:
    """Identical in every respect to `modules.entries.repository`'s own
    function of the same name — see that module's docstring for the full
    explanation of why this exists and why it resets to `DEFERRED`
    afterward. Forked, not imported, for the reason this module's own
    docstring gives."""
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def account_ids_by_code(conn: Connection, codes: list[str]) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT code, id FROM accounts WHERE code = ANY(:codes)"), {"codes": codes}
    ).mappings()
    return {r["code"]: r["id"] for r in rows}


def staging_scenario_id(conn: Connection) -> int | None:
    """The one scenario `is_staging` names — same query as `modules.
    imports.repository.staging_scenario_id`, forked for the same reason.
    `db/schema.sql`'s `uq_one_staging_scenario` caps this at one row,
    ever."""
    row = conn.execute(text("SELECT id FROM scenarios WHERE is_staging")).mappings().first()
    return row["id"] if row else None


def sync_tags(conn: Connection, table: str, id_col: str, obj_id: int, tag_names: list[str]) -> None:
    """Full replace of one row's tags in whichever junction table it
    owns — ported from `_sync_tags`, shared here (unlike `modules/
    entries/repository.py`'s own entry-specific `sync_entry_tags`)
    because this module has two callers of the *generic* shape:
    `scheduled_entry_tags`/`scheduled_entry_id` for a schedule, `entry_
    template_tags`/`template_id` for a template. `ON CONFLICT ... DO
    UPDATE SET is_active = TRUE` (not a no-op) is deliberate, same
    reasoning as `modules.entries.repository.sync_entry_tags`: typing an
    existing tag's name here is exactly the signal that it's back in
    use, so this quietly reactivates one that was archived rather than
    leaving it archived-but-attached."""
    conn.execute(text(f"DELETE FROM {table} WHERE {id_col} = :obj_id"), {"obj_id": obj_id})
    for name in tag_names:
        tag_id = conn.execute(text("""
            INSERT INTO tags (name) VALUES (:name)
            ON CONFLICT (name) DO UPDATE SET is_active = TRUE
            RETURNING id
        """), {"name": name}).mappings().one()["id"]
        conn.execute(
            text(f"INSERT INTO {table} ({id_col}, tag_id) VALUES (:obj_id, :tag_id)"),
            {"obj_id": obj_id, "tag_id": tag_id})


def sync_journal_entry_tags(conn: Connection, entry_id: str, tag_names: list[str]) -> None:
    """`sync_tags` against `journal_entry_tags`/`entry_id` specifically —
    forked from `modules.entries.repository.sync_entry_tags` rather than
    imported, same "deletable on its own" reasoning. `materialize_due_
    schedules` calls this to carry a schedule's own tags onto each
    staged occurrence."""
    sync_tags(conn, "journal_entry_tags", "entry_id", entry_id, tag_names)


# ---------------------------------------------------------------------------
# Scheduled entries
# ---------------------------------------------------------------------------

def scheduled_all(conn: Connection) -> list[dict]:
    """Every schedule, soonest-due first."""
    rows = conn.execute(text("""
        SELECT se.*, s.code AS scenario_code, s.name AS scenario_name,
               p.name AS payee_name,
               (SELECT COUNT(*) FROM scheduled_entry_lines
                 WHERE scheduled_entry_id = se.id) AS line_count,
               (SELECT COALESCE(SUM(debit), 0) FROM scheduled_entry_lines
                 WHERE scheduled_entry_id = se.id) AS total_amount
          FROM scheduled_entries se
          JOIN scenarios s ON s.id = se.target_scenario_id
          LEFT JOIN payees p ON p.id = se.payee_id
         ORDER BY se.next_date, se.id
    """)).mappings()
    return [dict(r) for r in rows]


def insert_schedule(conn: Connection, *, description: str, reference: str | None,
                     payee_id: int | None, target_scenario_id: int, interval_unit: str,
                     interval_count: int, next_date) -> int:
    row = conn.execute(text("""
        INSERT INTO scheduled_entries
               (description, reference, payee_id, target_scenario_id,
                interval_unit, interval_count, next_date)
        VALUES (:description, :reference, :payee_id, :target_scenario_id,
                :interval_unit, :interval_count, :next_date)
        RETURNING id
    """), {"description": description, "reference": reference, "payee_id": payee_id,
           "target_scenario_id": target_scenario_id, "interval_unit": interval_unit,
           "interval_count": interval_count, "next_date": next_date}).mappings().one()
    return row["id"]


def insert_schedule_line(conn: Connection, *, scheduled_entry_id: int, line_no: int,
                          account_id: int, amount: Decimal, memo: str | None) -> None:
    conn.execute(text("""
        INSERT INTO scheduled_entry_lines (scheduled_entry_id, line_no, account_id, amount, memo)
        VALUES (:scheduled_entry_id, :line_no, :account_id, :amount, :memo)
    """), {"scheduled_entry_id": scheduled_entry_id, "line_no": line_no,
           "account_id": account_id, "amount": amount, "memo": memo})


def toggle_schedule_active(conn: Connection, scheduled_id: int) -> dict | None:
    """`None` on an unknown id — see this module's own docstring for
    why."""
    row = conn.execute(text("""
        UPDATE scheduled_entries SET is_active = NOT is_active WHERE id = :id
        RETURNING id, description, is_active
    """), {"id": scheduled_id}).mappings().first()
    return dict(row) if row else None


def due_schedules(conn: Connection) -> list[dict]:
    """Every active schedule whose `next_date` has arrived. `ORDER BY id`
    (not `next_date`, unlike `scheduled_all`): the order two schedules
    due on the same day materialize in doesn't matter, but it needs to
    be *some* fixed order for the loop to be deterministic."""
    rows = conn.execute(text("""
        SELECT * FROM scheduled_entries
         WHERE is_active AND next_date <= CURRENT_DATE
         ORDER BY id
    """)).mappings()
    return [dict(r) for r in rows]


def schedule_lines(conn: Connection, scheduled_entry_id: int) -> list[dict]:
    rows = conn.execute(text("""
        SELECT line_no, account_id, amount, memo FROM scheduled_entry_lines
         WHERE scheduled_entry_id = :id ORDER BY line_no
    """), {"id": scheduled_entry_id}).mappings()
    return [dict(r) for r in rows]


def schedule_tag_names(conn: Connection, scheduled_entry_id: int) -> list[str]:
    rows = conn.execute(text("""
        SELECT tg.name FROM scheduled_entry_tags st
          JOIN tags tg ON tg.id = st.tag_id
         WHERE st.scheduled_entry_id = :id
    """), {"id": scheduled_entry_id}).mappings()
    return [r["name"] for r in rows]


def insert_staged_occurrence(conn: Connection, *, scenario_id: int, entry_date, description: str,
                              reference: str | None, payee_id: int | None,
                              scheduled_entry_id: int) -> str:
    """One staged `journal_entries` header for a due occurrence.
    `scheduled_entry_id` is what satisfies `fn_staging_manual_entry_
    guard`, the same role `modules.imports.repository.
    insert_staged_entry`'s `import_batch_id` plays for the other
    producer. No `created_by_user_id`: an occurrence sitting in Staging
    isn't yet anyone's manual posting, same reasoning `modules.imports.
    repository.insert_staged_entry`'s own docstring gives — that only
    gets set on the *approved* copy `modules.staging.service.
    approve_entry` creates."""
    row = conn.execute(text("""
        INSERT INTO journal_entries
               (scenario_id, entry_date, description, reference, payee_id, scheduled_entry_id)
        VALUES (:scenario_id, :entry_date, :description, :reference, :payee_id, :scheduled_entry_id)
        RETURNING id
    """), {"scenario_id": scenario_id, "entry_date": entry_date, "description": description,
           "reference": reference, "payee_id": payee_id,
           "scheduled_entry_id": scheduled_entry_id}).mappings().one()
    return row["id"]


def insert_staged_line(conn: Connection, *, entry_id: str, line_no: int, account_id: int,
                        amount: Decimal, memo: str | None) -> None:
    """Identical shape to `modules.entries.repository.insert_line` —
    `amount` is the canonical signed figure (debit > 0, credit < 0)."""
    conn.execute(text("""
        INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
        VALUES (:entry_id, :line_no, :account_id, :amount, :memo)
    """), {"entry_id": entry_id, "line_no": line_no, "account_id": account_id,
           "amount": amount, "memo": memo})


def advance_next_date(conn: Connection, scheduled_id: int, next_date) -> None:
    conn.execute(
        text("UPDATE scheduled_entries SET next_date = :next_date WHERE id = :id"),
        {"next_date": next_date, "id": scheduled_id})


# ---------------------------------------------------------------------------
# Entry templates
# ---------------------------------------------------------------------------

def templates_all(conn: Connection) -> list[dict]:
    """Header rows only, name-ordered. `service.list_templates` nests
    each template's own `lines`/`tags` (via `template_lines_for`/
    `template_tags_for` below) directly under it — see
    `modules/entries/service.py`'s own docstring for why that nested
    shape is preferred over parallel dicts."""
    rows = conn.execute(text("""
        SELECT t.id, t.name, t.description, t.reference, t.payee_id, p.name AS payee_name
          FROM entry_templates t
          LEFT JOIN payees p ON p.id = t.payee_id
         ORDER BY t.name
    """)).mappings()
    return [dict(r) for r in rows]


def template_lines_for(conn: Connection, template_ids: list[int]) -> list[dict]:
    rows = conn.execute(text("""
        SELECT l.template_id, a.code, l.debit, l.credit, l.memo
          FROM entry_template_lines l
          JOIN accounts a ON a.id = l.account_id
         WHERE l.template_id = ANY(:ids)
         ORDER BY l.template_id, l.line_no
    """), {"ids": template_ids}).mappings()
    return [dict(r) for r in rows]


def template_tags_for(conn: Connection, template_ids: list[int]) -> list[dict]:
    rows = conn.execute(text("""
        SELECT ett.template_id, tg.name FROM entry_template_tags ett
          JOIN tags tg ON tg.id = ett.tag_id
         WHERE ett.template_id = ANY(:ids) ORDER BY tg.name
    """), {"ids": template_ids}).mappings()
    return [dict(r) for r in rows]


def insert_template(conn: Connection, *, name: str, description: str, reference: str | None,
                     payee_id: int | None) -> int:
    row = conn.execute(text("""
        INSERT INTO entry_templates (name, description, reference, payee_id)
        VALUES (:name, :description, :reference, :payee_id)
        RETURNING id
    """), {"name": name, "description": description, "reference": reference,
           "payee_id": payee_id}).mappings().one()
    return row["id"]


def insert_template_line(conn: Connection, *, template_id: int, line_no: int, account_id: int,
                          amount: Decimal, memo: str | None) -> None:
    conn.execute(text("""
        INSERT INTO entry_template_lines (template_id, line_no, account_id, amount, memo)
        VALUES (:template_id, :line_no, :account_id, :amount, :memo)
    """), {"template_id": template_id, "line_no": line_no, "account_id": account_id,
           "amount": amount, "memo": memo})


def delete_template(conn: Connection, template_id: int) -> int:
    """Returns the rowcount — `service.delete_template` is what checks
    it and raises. See this module's own docstring for why."""
    result = conn.execute(
        text("DELETE FROM entry_templates WHERE id = :id"), {"id": template_id})
    return result.rowcount
