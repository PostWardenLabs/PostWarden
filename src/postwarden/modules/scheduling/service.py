"""Validation and orchestration for the scheduling module — scheduled
entries and entry templates. Every function here takes a SQLAlchemy
`Connection` and reads/writes through `repository.py`, never raw SQL of
its own, same convention every prior module established.

`materialize_due_schedules` is called from `main.py`'s own middleware on
every authenticated request, wrapped in a bare `try/except Exception:
pass` — there's no task runner in this deployment, so "auto-post on the
date" is done lazily on request rather than by a real cron. See
`main.py`'s `advance_due_schedules` for the wiring."""
from datetime import date

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...domain.entry import parse_lines, parse_tags
from ...domain.periods import advance_date
from ...errors import pg_message
from . import repository as repo

# ---------------------------------------------------------------------------
# Scheduled entries
# ---------------------------------------------------------------------------

def list_schedules(conn: Connection) -> list[dict]:
    return repo.scheduled_all(conn)


def create_schedule(conn: Connection, *, description: str, reference: str | None,
                     payee_id: int | None, target_scenario_id: int, interval_unit: str,
                     interval_count: int, next_date: date | None, tags: str,
                     accounts: list[str], debits: list[str], credits: list[str],
                     memos: list[str]) -> int:
    """`interval_unit` isn't checked against the three valid values
    here — `schemas.IntervalUnit`'s `Literal` already rejected a bad
    value before this function is ever called from `router.py` (direct
    callers, e.g. tests, are expected to pass one of the three valid
    strings, same trust boundary `domain.entry.parse_lines` places on
    its own callers).

    The manual `total != 0` balance check is real here, unlike `modules.
    entries.service.create_entry` (which leaves that check entirely to
    `journal_lines`' own `DEFERRABLE` constraint trigger,
    `domain.entry.parse_lines`'s own docstring explains why): `scheduled_
    entry_lines` carries no equivalent trigger at all, `db/schema.sql`'s
    own `CHECK (amount <> 0)` per line is as far as the schema goes, so
    an unbalanced schedule is caught here in app code or not at all."""
    lines = parse_lines(accounts, debits, credits, memos)
    total = sum(ln["amount"] for ln in lines)
    if total != 0:
        raise ValueError("Schedule lines must balance (debits = credits)")
    description = (description or "").strip()
    if not description:
        raise ValueError("Description is required")
    if interval_count <= 0:
        raise ValueError("Repeat count must be positive")
    tag_names = parse_tags(tags)

    codes = {ln["code"] for ln in lines}
    found = repo.account_ids_by_code(conn, list(codes))
    missing = codes - found.keys()
    if missing:
        raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

    sched_id = repo.insert_schedule(
        conn, description=description, reference=reference, payee_id=payee_id,
        target_scenario_id=target_scenario_id, interval_unit=interval_unit,
        interval_count=interval_count, next_date=next_date or date.today())
    for n, ln in enumerate(lines, start=1):
        repo.insert_schedule_line(conn, scheduled_entry_id=sched_id, line_no=n,
                                   account_id=found[ln["code"]], amount=ln["amount"], memo=ln["memo"])
    if tag_names:
        repo.sync_tags(conn, "scheduled_entry_tags", "scheduled_entry_id", sched_id, tag_names)
    return sched_id


def toggle_schedule_active(conn: Connection, scheduled_id: int) -> dict:
    row = repo.toggle_schedule_active(conn, scheduled_id)
    if row is None:
        raise ValueError(f"Schedule #{scheduled_id} not found")
    return row


def materialize_due_schedules(conn: Connection) -> tuple[list[int], list[str]]:
    """Posts a staged occurrence for every active, due schedule and
    advances its `next_date`. Returns `(materialized_ids, errors)`, the
    same "collect successes and failures separately" shape `modules.
    entries.service.reverse_entries_bulk` already uses, for the identical
    structural reason: **one schedule per `Connection.begin_nested()`
    SAVEPOINT, not a bare loop.** `db.get_connection()` gives the whole
    request one transaction, so without the SAVEPOINT a bad schedule
    would abort every schedule after it too, not just itself.
    `repo.check_deferred_constraints` inside each SAVEPOINT is what
    forces the balance/has-lines triggers to run at a point this
    function's own `try/except` (not a 500 raised who-knows-when after
    this function already returned) can catch — see `repository.py`'s
    own docstring for the full explanation, the same one `modules.
    entries.repository.check_deferred_constraints` already gave for the
    Journal's own write path.

    A schedule with no lines is skipped, `next_date` left untouched —
    nothing to post, and silently advancing the date would mean the
    occurrence is just lost rather than caught on the next pass."""
    due = repo.due_schedules(conn)
    if not due:
        return [], []
    staging_id = repo.staging_scenario_id(conn)
    if staging_id is None:
        return [], []  # schema migrated but the seed row hasn't landed yet

    materialized: list[int] = []
    errors: list[str] = []
    for sched in due:
        lines = repo.schedule_lines(conn, sched["id"])
        if not lines:
            continue
        tag_names = repo.schedule_tag_names(conn, sched["id"])
        try:
            with conn.begin_nested():
                entry_id = repo.insert_staged_occurrence(
                    conn, scenario_id=staging_id, entry_date=sched["next_date"],
                    description=sched["description"], reference=sched["reference"],
                    payee_id=sched["payee_id"], scheduled_entry_id=sched["id"])
                for ln in lines:
                    repo.insert_staged_line(conn, entry_id=entry_id, line_no=ln["line_no"],
                                             account_id=ln["account_id"], amount=ln["amount"],
                                             memo=ln["memo"])
                if tag_names:
                    repo.sync_journal_entry_tags(conn, entry_id, tag_names)
                repo.check_deferred_constraints(conn)
                repo.advance_next_date(
                    conn, sched["id"],
                    advance_date(sched["next_date"], sched["interval_unit"], sched["interval_count"]))
            materialized.append(sched["id"])
        except SQLAlchemyError as e:
            errors.append(pg_message(e))
    return materialized, errors


# ---------------------------------------------------------------------------
# Entry templates
# ---------------------------------------------------------------------------

def list_templates(conn: Connection) -> list[dict]:
    """Each template comes back with its own `lines`/`tags` nested
    directly under it — see `modules/entries/service.py`'s own docstring
    for why that nested shape is preferred over parallel dicts."""
    templates = repo.templates_all(conn)
    ids = [t["id"] for t in templates]
    lines_by_t: dict[int, list] = {}
    tags_by_t: dict[int, list] = {}
    if ids:
        for ln in repo.template_lines_for(conn, ids):
            lines_by_t.setdefault(ln["template_id"], []).append({
                "code": ln["code"],
                "debit": str(ln["debit"]) if ln["debit"] else None,
                "credit": str(ln["credit"]) if ln["credit"] else None,
                "memo": ln["memo"],
            })
        for tg in repo.template_tags_for(conn, ids):
            tags_by_t.setdefault(tg["template_id"], []).append(tg["name"])
    return [{**t, "lines": lines_by_t.get(t["id"], []), "tags": tags_by_t.get(t["id"], [])}
            for t in templates]


def create_template(conn: Connection, *, name: str, description: str, reference: str | None,
                     payee_id: int | None, tags: str, accounts: list[str], debits: list[str],
                     credits: list[str], memos: list[str]) -> int:
    """Ported from `create_template`'s validation-then-insert body. Same
    manual balance check as `create_schedule`, and for the identical
    reason — see that function's own docstring."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Template name is required")
    lines = parse_lines(accounts, debits, credits, memos)
    total = sum(ln["amount"] for ln in lines)
    if total != 0:
        raise ValueError("Template lines must balance (debits = credits)")
    description = (description or "").strip()
    if not description:
        raise ValueError("Description is required")
    tag_names = parse_tags(tags)

    codes = {ln["code"] for ln in lines}
    found = repo.account_ids_by_code(conn, list(codes))
    missing = codes - found.keys()
    if missing:
        raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

    tpl_id = repo.insert_template(conn, name=name, description=description,
                                   reference=reference, payee_id=payee_id)
    for n, ln in enumerate(lines, start=1):
        repo.insert_template_line(conn, template_id=tpl_id, line_no=n,
                                   account_id=found[ln["code"]], amount=ln["amount"], memo=ln["memo"])
    if tag_names:
        repo.sync_tags(conn, "entry_template_tags", "template_id", tpl_id, tag_names)
    return tpl_id


def delete_template(conn: Connection, template_id: int) -> None:
    if repo.delete_template(conn, template_id) == 0:
        raise ValueError(f"Template #{template_id} not found")
