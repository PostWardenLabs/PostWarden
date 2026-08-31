"""Entry assembly and mutation — the Journal backend's business logic.
Every function here takes a SQLAlchemy `Connection` (from
`db.get_connection()`) as its first argument and reads/writes through
`repository.py` — never raw SQL of its own, same convention
`modules/reports/service.py` established.

**`reverse_entries_bulk` uses `Connection.begin_nested()` (a SAVEPOINT)
per entry, not a bare loop.** `db.get_connection()` gives the whole
request *one* transaction, so a bare loop over entries would mean one
already-reversed or locked-scenario entry failing takes every entry
after it down too — Postgres aborts an entire transaction on the first
error inside it, even though the later entries would have succeeded
standalone. A `SAVEPOINT` per entry (`conn.begin_nested()`) gives each
entry true independence inside the one shared transaction: a failed
entry rolls back only to its own savepoint, leaving every entry already
processed (and the ones still to come) unaffected.
"""
from datetime import date

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...domain.entry import parse_lines, parse_tags
from ...errors import pg_message
from . import repository as repo

ENTRIES_PAGE_SIZE = 50


def list_entries(conn: Connection, *, scenario: str = "", date_from: str = "", date_to: str = "",
                  qtext: str = "", tags: str = "", account: str = "", payee: str = "",
                  amount_op: str = "", amount_value: str = "", amount_value2: str = "",
                  hide_reversed: bool = False, entry_id: str = "", page: int = 1,
                  page_size: int = ENTRIES_PAGE_SIZE) -> dict:
    """Filtered, paginated Journal listing. Each entry comes back with
    its own `lines`/`tags` nested directly under it — one JSON object
    per entry — so a JSON API consumer has no grouping-by-id left to
    redo itself."""
    try:
        tag_list = parse_tags(tags) if tags else []
    except ValueError:
        tag_list = []  # a hand-edited query string with a malformed tag; ignore it
    where, params = repo.build_filter(
        scenario=scenario, date_from=date_from or None, date_to=date_to or None, qtext=qtext,
        tag_list=tag_list, account=account, payee=payee, amount_op=amount_op,
        amount_value=amount_value, amount_value2=amount_value2, hide_reversed=hide_reversed,
        entry_id=entry_id)
    page = max(page, 1)
    # One extra row purely to know whether a next page exists, trimmed
    # back off below.
    rows = repo.list_entries(conn, where, params, page_size + 1, (page - 1) * page_size)
    has_next = len(rows) > page_size
    rows = rows[:page_size]

    ids = [r["id"] for r in rows]
    lines_by_entry: dict[str, list] = {}
    tags_by_entry: dict[str, list] = {}
    if ids:
        for ln in repo.lines_for_entries(conn, ids):
            lines_by_entry.setdefault(ln["entry_id"], []).append(ln)
        for tg in repo.tags_for_entries(conn, ids):
            tags_by_entry.setdefault(tg["entry_id"], []).append(tg["name"])

    entries = [{**r, "lines": lines_by_entry.get(r["id"], []), "tags": tags_by_entry.get(r["id"], [])}
               for r in rows]
    return {"entries": entries, "page": page, "page_size": page_size,
            "has_next": has_next, "has_prev": page > 1}


def export_rows(conn: Connection, *, scenario: str = "", date_from: str = "", date_to: str = "",
                 qtext: str = "", tags: str = "", account: str = "", payee: str = "",
                 amount_op: str = "", amount_value: str = "", amount_value2: str = "",
                 hide_reversed: bool = False, entry_id: str = "", group_legs: bool = False) -> list[dict]:
    """Every journal line matching the current filters — not just the
    current page, unlike `list_entries` above. Same filters, same
    `WHERE` clause as `list_entries`, so what a caller sees in the
    Journal is exactly what they'd export (the reason `build_filter`
    lives in `repository.py` rather than being duplicated here)."""
    try:
        tag_list = parse_tags(tags) if tags else []
    except ValueError:
        tag_list = []  # a hand-edited query string with a malformed tag; ignore it
    where, params = repo.build_filter(
        scenario=scenario, date_from=date_from or None, date_to=date_to or None, qtext=qtext,
        tag_list=tag_list, account=account, payee=payee, amount_op=amount_op,
        amount_value=amount_value, amount_value2=amount_value2, hide_reversed=hide_reversed,
        entry_id=entry_id)
    return repo.export_rows(conn, where, params, group_legs=group_legs)


def create_entry(conn: Connection, *, entry_date: date | None, scenario_id: int, description: str,
                  reference: str | None, tags: str, payee_id: int | None, accounts: list[str],
                  debits: list[str], credits: list[str], memos: list[str],
                  created_by_user_id: int | None = None) -> str:
    """Ported from `create_entry`'s validation-then-insert body.
    `accounts`/`debits`/`credits`/`memos` are the router's own unzip of
    `schemas.CreateEntryRequest.lines` — see that module's docstring for
    why the parallel-list shape survives into `domain.entry.parse_lines`
    unchanged.

    Calls `repository.check_deferred_constraints` right after the last
    line insert, before returning — see `repository.py`'s own docstring
    for why that's needed at all given `db.get_connection()`'s one-
    transaction-per-request design: without it, an unbalanced entry
    would still be rejected, just as an unhandled 500 raised after this
    function (and the route) already returned, instead of the
    `ValueError`-shaped 400 a caller can actually act on."""
    lines = parse_lines(accounts, debits, credits, memos)
    description = (description or "").strip()
    if not description:
        raise ValueError("Description is required")
    tag_names = parse_tags(tags)

    codes = {ln["code"] for ln in lines}
    found = repo.account_ids_by_code(conn, list(codes))
    missing = codes - found.keys()
    if missing:
        raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

    entry_id = repo.insert_entry(
        conn, scenario_id=scenario_id, entry_date=entry_date or date.today(),
        description=description, reference=reference, payee_id=payee_id,
        created_by_user_id=created_by_user_id)
    for n, ln in enumerate(lines, start=1):
        repo.insert_line(conn, entry_id=entry_id, line_no=n, account_id=found[ln["code"]],
                          amount=ln["amount"], memo=ln["memo"])
    if tag_names:
        repo.sync_entry_tags(conn, entry_id, tag_names)
    repo.check_deferred_constraints(conn)
    return entry_id


def reverse_entry(conn: Connection, entry_id: str, user_id: int | None = None) -> str:
    """Posts the reversing entry for one already-posted entry — ported
    from `_reverse_one_entry`. Raises `ValueError` for anything that
    isn't a straightforward reversal (not found, already reversed); a
    locked scenario or similar still surfaces as `SQLAlchemyError` from
    the database itself. Returns the new entry's id."""
    orig = repo.entry_for_reverse(conn, entry_id)
    if not orig:
        raise ValueError(f"Entry #{entry_id} not found")
    already = repo.reversed_by(conn, entry_id)
    if already:
        raise ValueError(f"Entry #{entry_id} was already reversed by #{already}")

    new_id = repo.insert_entry(
        conn, scenario_id=orig["scenario_id"], entry_date=date.today(),
        description=f"Reversal of #{entry_id} — {orig['description']}",
        reference=orig["reference"], payee_id=orig["payee_id"],
        created_by_user_id=user_id, reverses_entry_id=entry_id)
    repo.copy_lines_reversed(conn, new_id, entry_id)
    repo.copy_tags(conn, new_id, entry_id)
    repo.check_deferred_constraints(conn)
    return new_id


def reverse_entries_bulk(conn: Connection, entry_ids: list[str],
                          user_id: int | None = None) -> tuple[list[str], list[str]]:
    """Bulk sibling of `reverse_entry` — a `SAVEPOINT` per entry
    (`conn.begin_nested()`, see this module's own docstring for why)
    collects successes and errors separately, so one already-reversed
    or locked-scenario entry in the batch doesn't stop the rest from
    going through."""
    reversed_ids: list[str] = []
    errors: list[str] = []
    for eid in entry_ids:
        try:
            with conn.begin_nested():
                reversed_ids.append(reverse_entry(conn, eid, user_id))
        except ValueError as e:
            errors.append(str(e))
        except SQLAlchemyError as e:
            errors.append(pg_message(e))
    return reversed_ids, errors


def edit_entries_tags(conn: Connection, entry_ids: list[str], action: str, tag: str) -> str:
    """Add or remove one tag across whatever's checked. Returns the tag
    name, echoed back for a client that built the request from a raw
    comma string and wants back the exact normalized name."""
    if not entry_ids:
        raise ValueError("No entries selected")
    tag_names = parse_tags(tag)
    if len(tag_names) != 1:
        raise ValueError("Expected exactly one tag")
    tag_name = tag_names[0]
    if action == "add":
        repo.add_tag_to_entries(conn, entry_ids, tag_name)
    elif action == "remove":
        repo.remove_tag_from_entries(conn, entry_ids, tag_name)
    else:
        raise ValueError(f"Unknown action {action!r}")
    return tag_name


def edit_description(conn: Connection, entry_id: str, description: str) -> str:
    """Works on any entry, posted or still pending in Staging —
    `fn_entries_guard` allows changing `description`/`reference` on a
    posted entry (SPEC.md's tag-editing reasoning: organizational, not
    a fact about the transaction)."""
    description = (description or "").strip()
    if not description:
        raise ValueError("Description can't be empty")
    if repo.update_description(conn, entry_id, description) == 0:
        raise ValueError(f"Entry #{entry_id} not found")
    return description


def edit_line_memo(conn: Connection, line_id: int, memo: str | None) -> str:
    """Returns `""` (not `None`) for a cleared memo."""
    memo = (memo or "").strip() or None
    if repo.update_line_memo(conn, line_id, memo) == 0:
        raise ValueError(f"Line {line_id} not found")
    return memo or ""
