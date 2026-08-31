"""Raw SQL access for the staging module — the layover a scheduled
entry's occurrence or a CSV import row sits in until a human approves
it. Same conventions `modules/entries/repository.py` established:
every function takes a SQLAlchemy `Connection` and returns plain
dicts/lists/scalars, `Decimal` for money, never `float`.

**Forks `modules/entries/repository.py`'s shared filter fragments and a
few small helpers (`account_ids_by_code`, `insert_entry`/`insert_line`,
`sync_entry_tags`, tag/line lookups) rather than importing them.** A
vertical slice's own test is "a module should be deletable on its own,"
and importing from a sibling module fails that test in exactly the
direction that matters — deleting `modules/entries/` would break
`modules/staging/` even though nothing about approving a staged entry
actually depends on the Journal. The shared fragments (date range,
free-text search, tags, account, payee, amount operator) are ~25 lines;
the duplication cost is small and paid once, while the coupling cost of
importing would compound with every future module that also needs entry
filtering (`budget`, `imports`).

**No `target_scenario`/`accounts` picker payload in `staged_entry`'s
response, and no full scenario row either** — same "don't reach into a
sibling module" reasoning `modules/reports/repository.py` and
`modules/entries/repository.py` both apply to `modules/reference/`.
`service.get_edit_data` returns `target_scenario_id` (a fact about
*this* staged entry, computed from its own producer) but not the
scenario's own name/code or the postable-accounts-for-that-scenario
list — the frontend fetches those from `modules/reference/` instead.

**One small consolidation:** two near-identical "resolve this staged
entry's target scenario, default to ACTUAL, and validate it's actually
pending" checks are collapsed into `service._validate_pending`, the one
function both `approve_entry` and the edit/reject/merge paths call,
using the clearer of the two error messages throughout. See
`service.py`'s own docstring."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.engine import Connection

AMOUNT_OPS = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}


def check_deferred_constraints(conn: Connection) -> None:
    """Identical in every respect to `modules.entries.repository`'s own
    function of the same name — see that module's docstring for the full
    explanation of why this exists and why it resets to `DEFERRED`
    afterward. Forked, not imported, for the same reason the rest of this
    file is: a vertical slice should be deletable on its own."""
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def account_ids_by_code(conn: Connection, codes: list[str]) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT code, id FROM accounts WHERE code = ANY(:codes)"), {"codes": codes}
    ).mappings()
    return {r["code"]: r["id"] for r in rows}


def actual_scenario_id(conn: Connection) -> int | None:
    """The fallback destination when a staged entry's own producer
    (schedule or import batch) didn't say where it's headed — ported
    from the `SELECT id FROM scenarios WHERE code = 'ACTUAL'` inline in
    both `approve_staging_entries` and `_pending_staging_entry`."""
    row = conn.execute(text("SELECT id FROM scenarios WHERE code = 'ACTUAL'")).mappings().first()
    return row["id"] if row else None


def build_filter(*, date_from: str | None = None, date_to: str | None = None, qtext: str = "",
                  tag_list: list[str] | None = None, account: str = "", payee: str = "",
                  amount_op: str = "", amount_value: str = "", amount_value2: str = "",
                  target_scenario: str = "") -> tuple[list[str], dict]:
    """WHERE-clause fragments + named bind params for Staging's own
    filter bar — ported from `_staging_filter`. Unconditional
    `e.promoted_entry_id IS NULL`: Staging's page only ever shows what's
    still pending, the same role `modules/entries/repository.py`'s own
    unconditional `NOT s.is_staging` plays for the Journal. `target_
    scenario` is Staging's one filter field the Journal has no
    equivalent for (see this function's own `ts`/`ib_ts` aliases, which
    only exist in `service.list_pending`'s query) — every row here
    already belongs to the one real Staging scenario, so filtering
    *that* would be meaningless; what varies row to row is where each
    entry is headed once approved."""
    where: list[str] = ["e.promoted_entry_id IS NULL"]
    params: dict = {}
    if target_scenario:
        where.append("COALESCE(ts.code, ib_ts.code) = :target_scenario")
        params["target_scenario"] = target_scenario
    if date_from:
        where.append("e.entry_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("e.entry_date <= :date_to")
        params["date_to"] = date_to
    if qtext:
        where.append("(e.description ILIKE :qtext OR e.reference ILIKE :qtext)")
        params["qtext"] = f"%{qtext}%"
    if tag_list:
        where.append("""e.id IN (SELECT jet.entry_id FROM journal_entry_tags jet
                                   JOIN tags tg ON tg.id = jet.tag_id
                                  WHERE tg.name = ANY(:tags))""")
        params["tags"] = tag_list
    if account:
        where.append("""e.id IN (SELECT jl.entry_id FROM journal_lines jl
                                   JOIN accounts a ON a.id = jl.account_id
                                  WHERE a.code = :account)""")
        params["account"] = account
    if payee:
        where.append("p.name = :payee")
        params["payee"] = payee
    if amount_op == "between" and amount_value and amount_value2:
        try:
            lo, hi = Decimal(amount_value).quantize(Decimal("0.01")), Decimal(amount_value2).quantize(Decimal("0.01"))
        except InvalidOperation:
            lo = hi = None
        if lo is not None:
            lo, hi = sorted((lo, hi))
            where.append("""(SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                               WHERE l.entry_id = e.id) BETWEEN :amount_lo AND :amount_hi""")
            params["amount_lo"], params["amount_hi"] = lo, hi
    elif amount_op in AMOUNT_OPS and amount_value:
        try:
            amount_num = Decimal(amount_value).quantize(Decimal("0.01"))
        except InvalidOperation:
            amount_num = None
        if amount_num is not None:
            op = AMOUNT_OPS[amount_op]
            where.append(f"""(SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                               WHERE l.entry_id = e.id) {op} :amount_value""")
            params["amount_value"] = amount_num
    return where, params


def list_pending_entries(conn: Connection, where: list[str], params: dict) -> list[dict]:
    """Every entry sitting in Staging that matches `where`/`params` — no
    `LIMIT`/`OFFSET`, since this page is never large enough to need
    pagination. `target_scenario_code`/`_name` and each row's own origin
    (`schedule_description`/`import_filename`/`import_date`) are what
    the Staging screen shows per row ("Created from schedule 'Rent'"/
    "Imported from file 'march.csv'") — both joins are LEFT since an
    entry carries at most one of the two, never both."""
    sql = f"""
        SELECT e.id, e.entry_date, e.description, e.reference, e.payee_id,
               p.name AS payee_name,
               COALESCE(ts.code, ib_ts.code) AS target_scenario_code,
               COALESCE(ts.name, ib_ts.name) AS target_scenario_name,
               se.description AS schedule_description,
               ib.filename AS import_filename,
               ib.created_at::date AS import_date,
               (SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_debits
          FROM journal_entries e
          JOIN scenarios stg ON stg.id = e.scenario_id AND stg.is_staging
          LEFT JOIN scheduled_entries se ON se.id = e.scheduled_entry_id
          LEFT JOIN scenarios ts ON ts.id = se.target_scenario_id
          LEFT JOIN import_batches ib ON ib.id = e.import_batch_id
          LEFT JOIN scenarios ib_ts ON ib_ts.id = ib.target_scenario_id
          LEFT JOIN payees p ON p.id = e.payee_id
         WHERE {' AND '.join(where)}
         ORDER BY e.entry_date, e.seq
    """
    rows = conn.execute(text(sql), params).mappings()
    return [dict(r) for r in rows]


def lines_for_entries(conn: Connection, entry_ids: list[str]) -> list[dict]:
    """Debit/credit split, same shape as `modules.entries.repository`'s
    function of the same name — used to nest lines under each entry in
    `service.list_pending`/`service.get_edit_data`."""
    rows = conn.execute(text("""
        SELECT l.id, l.entry_id, l.line_no, l.debit, l.credit, l.memo,
               a.code AS account_code, a.name AS account_name
          FROM journal_lines l
          JOIN accounts a ON a.id = l.account_id
         WHERE l.entry_id = ANY(:entry_ids)
         ORDER BY l.entry_id, l.line_no
    """), {"entry_ids": entry_ids}).mappings()
    return [dict(r) for r in rows]


def lines_for_entries_signed(conn: Connection, entry_ids: list[str]) -> list[dict]:
    """The signed-`amount` shape `service.find_duplicate_groups` needs
    (its fingerprint is `(account_id, amount)` pairs, and its `flow_
    label` sorts on sign) rather than `lines_for_entries`'s debit/credit
    split — ported from `_find_staging_duplicate_groups`'s own line
    query."""
    rows = conn.execute(text("""
        SELECT l.id, l.entry_id, l.account_id, l.amount, l.memo,
               a.code AS account_code, a.name AS account_name
          FROM journal_lines l
          JOIN accounts a ON a.id = l.account_id
         WHERE l.entry_id = ANY(:entry_ids)
         ORDER BY l.entry_id, l.line_no
    """), {"entry_ids": entry_ids}).mappings()
    return [dict(r) for r in rows]


def tags_for_entries(conn: Connection, entry_ids: list[str]) -> list[dict]:
    rows = conn.execute(text("""
        SELECT jet.entry_id, tg.name
          FROM journal_entry_tags jet
          JOIN tags tg ON tg.id = jet.tag_id
         WHERE jet.entry_id = ANY(:entry_ids)
         ORDER BY tg.name
    """), {"entry_ids": entry_ids}).mappings()
    return [dict(r) for r in rows]


def all_pending_entries_basic(conn: Connection) -> list[dict]:
    """Every entry currently sitting in the Staging scenario. Note this
    does **not** filter on `promoted_entry_id IS NULL`: an already-
    approved staging-origin entry is never moved or deleted (only
    `promoted_entry_id` gets set on it), so it stays a candidate for
    "Find duplicates" too. Left as-is rather than "fixed" — `staging/
    duplicates` has no test coverage pinning down whether that's a bug
    or deliberate, so changing it now would be a guess."""
    rows = conn.execute(text("""
        SELECT e.id, e.entry_date, e.description, e.reference, e.payee_id,
               p.name AS payee_name
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id AND s.is_staging
          LEFT JOIN payees p ON p.id = e.payee_id
         ORDER BY e.entry_date, e.seq
    """)).mappings()
    return [dict(r) for r in rows]


def staged_entry(conn: Connection, entry_id: str) -> dict | None:
    """The one entry `service._validate_pending` acts on — ported from
    `_pending_staging_entry`'s own lookup. Returns the raw joined row
    (including `is_staging`, `promoted_entry_id`, and the resolved-but-
    not-yet-defaulted `target_scenario_id`); `service.py` is what turns
    this into eligibility validation, matching the repository/service
    split `modules/entries/repository.py` already established."""
    row = conn.execute(text("""
        SELECT e.id, e.scenario_id, e.entry_date, e.description, e.reference,
               e.payee_id, e.promoted_entry_id, s.is_staging,
               COALESCE(se.target_scenario_id, ib.target_scenario_id) AS target_scenario_id
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id
          LEFT JOIN scheduled_entries se ON se.id = e.scheduled_entry_id
          LEFT JOIN import_batches ib ON ib.id = e.import_batch_id
         WHERE e.id = :entry_id
    """), {"entry_id": entry_id}).mappings().first()
    return dict(row) if row else None


def sync_entry_tags(conn: Connection, entry_id: str, tag_names: list[str]) -> None:
    """Identical to `modules.entries.repository`'s function of the same
    name — see that module's docstring for the `ON CONFLICT ... DO
    UPDATE SET is_active = TRUE` reactivation behavior."""
    conn.execute(text("DELETE FROM journal_entry_tags WHERE entry_id = :entry_id"),
                 {"entry_id": entry_id})
    for name in tag_names:
        tag_id = conn.execute(text("""
            INSERT INTO tags (name) VALUES (:name)
            ON CONFLICT (name) DO UPDATE SET is_active = TRUE
            RETURNING id
        """), {"name": name}).mappings().one()["id"]
        conn.execute(text("""
            INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (:entry_id, :tag_id)
        """), {"entry_id": entry_id, "tag_id": tag_id})


def insert_entry(conn: Connection, *, scenario_id: int, entry_date, description: str,
                  reference: str | None, payee_id: int | None,
                  created_by_user_id: int | None = None) -> str:
    """The new, posted entry `service.approve_entry` creates in the
    target scenario. Deliberately doesn't set `scheduled_entry_id`/
    `import_batch_id`: those name what *staged* this entry, and the
    newly-approved entry isn't itself a staged one."""
    row = conn.execute(text("""
        INSERT INTO journal_entries (scenario_id, entry_date, description, reference,
                                      payee_id, created_by_user_id)
        VALUES (:scenario_id, :entry_date, :description, :reference, :payee_id,
                :created_by_user_id)
        RETURNING id
    """), {"scenario_id": scenario_id, "entry_date": entry_date, "description": description,
           "reference": reference, "payee_id": payee_id,
           "created_by_user_id": created_by_user_id}).mappings().one()
    return row["id"]


def copy_lines(conn: Connection, new_entry_id: str, orig_entry_id: str) -> None:
    """Every line of `orig_entry_id`, unchanged, onto `new_entry_id` —
    ported from `approve_staging_entries`'s own `INSERT ... SELECT`. No
    sign flip (unlike `modules.entries.repository.copy_lines_reversed`):
    approving a staged entry posts it as-is, it isn't a reversal."""
    conn.execute(text("""
        INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
        SELECT :new_entry_id, line_no, account_id, amount, memo
          FROM journal_lines WHERE entry_id = :orig_entry_id
    """), {"new_entry_id": new_entry_id, "orig_entry_id": orig_entry_id})


def copy_tags(conn: Connection, new_entry_id: str, orig_entry_id: str) -> None:
    conn.execute(text("""
        INSERT INTO journal_entry_tags (entry_id, tag_id)
        SELECT :new_entry_id, tag_id FROM journal_entry_tags WHERE entry_id = :orig_entry_id
    """), {"new_entry_id": new_entry_id, "orig_entry_id": orig_entry_id})


def mark_promoted(conn: Connection, entry_id: str, new_entry_id: str) -> None:
    conn.execute(text("UPDATE journal_entries SET promoted_entry_id = :new_id WHERE id = :entry_id"),
                 {"new_id": new_entry_id, "entry_id": entry_id})


def update_entry_header(conn: Connection, entry_id: str, *, entry_date, description: str,
                         reference: str | None, payee_id: int | None) -> None:
    """The full-header update `service.save_edit` uses — ported from
    `staging_edit_save`'s own `UPDATE`. Unlike `modules.entries.
    repository.update_description` (posted-entry description/reference
    edits only, per `fn_entries_guard`), this also updates `entry_date`
    and `payee_id` — legal here specifically because the entry is still
    pending (`fn_entries_guard` relaxes every column while `is_staging
    AND promoted_entry_id IS NULL`, not just description/reference)."""
    conn.execute(text("""
        UPDATE journal_entries
           SET entry_date = :entry_date, description = :description,
               reference = :reference, payee_id = :payee_id
         WHERE id = :entry_id
    """), {"entry_date": entry_date, "description": description, "reference": reference,
           "payee_id": payee_id, "entry_id": entry_id})


def update_entry_fields(conn: Connection, entry_id: str, *, description: str,
                         reference: str | None, payee_id: int | None) -> None:
    """The narrower update `service.merge_duplicates` uses for the
    survivor entry. No `entry_date`, unlike `update_entry_header`: the
    merge popup never offers to change it."""
    conn.execute(text("""
        UPDATE journal_entries SET description = :description, reference = :reference,
                                    payee_id = :payee_id
         WHERE id = :entry_id
    """), {"description": description, "reference": reference, "payee_id": payee_id,
           "entry_id": entry_id})


def replace_lines(conn: Connection, entry_id: str, lines: list[dict]) -> None:
    """Delete-then-reinsert, the only shape an edit to a pending entry's
    lines can take — ported from `staging_edit_save`'s own comment:
    `journal_lines` stays `UPDATE`-blocked even for a pending Staging
    entry (see `db/schema.sql`'s `fn_lines_immutable`), only `DELETE` is
    relaxed. Both statements run in the caller's own open transaction, so
    the deferred balance/has-lines checks only ever see the final,
    complete set — never the momentarily-empty state in between. Each
    dict in `lines` needs `account_id`/`amount`/`memo`, the shape
    `service.save_edit`'s own `domain.entry.parse_lines` + account-code
    lookup already produces."""
    conn.execute(text("DELETE FROM journal_lines WHERE entry_id = :entry_id"), {"entry_id": entry_id})
    for n, ln in enumerate(lines, start=1):
        conn.execute(text("""
            INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
            VALUES (:entry_id, :line_no, :account_id, :amount, :memo)
        """), {"entry_id": entry_id, "line_no": n, "account_id": ln["account_id"],
               "amount": ln["amount"], "memo": ln["memo"]})


def line_ids_for_entry(conn: Connection, entry_id: str) -> list[int]:
    """Used by `service.merge_duplicates` to know which per-line memo
    overrides (keyed by line id in the request body) actually belong to
    the survivor entry — ported from `merge_staging_duplicates`'s own
    `SELECT id FROM journal_lines WHERE entry_id = %s` loop."""
    rows = conn.execute(text("SELECT id FROM journal_lines WHERE entry_id = :entry_id ORDER BY line_no"),
                         {"entry_id": entry_id}).mappings()
    return [r["id"] for r in rows]


def update_line_memo(conn: Connection, line_id: int, memo: str | None) -> None:
    conn.execute(text("UPDATE journal_lines SET memo = :memo WHERE id = :line_id"),
                 {"memo": memo, "line_id": line_id})


def delete_lines_for_entry(conn: Connection, entry_id: str) -> None:
    conn.execute(text("DELETE FROM journal_lines WHERE entry_id = :entry_id"), {"entry_id": entry_id})


def delete_entry(conn: Connection, entry_id: str) -> None:
    conn.execute(text("DELETE FROM journal_entries WHERE id = :entry_id"), {"entry_id": entry_id})


def delete_lines_for_entries(conn: Connection, entry_ids: list[str]) -> None:
    conn.execute(text("DELETE FROM journal_lines WHERE entry_id = ANY(:entry_ids)"),
                 {"entry_ids": entry_ids})


def delete_entries(conn: Connection, entry_ids: list[str]) -> None:
    conn.execute(text("DELETE FROM journal_entries WHERE id = ANY(:entry_ids)"),
                 {"entry_ids": entry_ids})
