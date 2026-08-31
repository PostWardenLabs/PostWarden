"""Staged-entry assembly and mutation — the layover a scheduled entry's
occurrence or a CSV import row sits in until approved. Every function
here takes a SQLAlchemy `Connection` and reads/writes through
`repository.py`, same convention `modules/entries/service.py`
established.

**`_validate_pending` is the one function every write path here calls**
(`approve_entry`, `get_edit_data`, `save_edit`, `reject_entry`, and
`merge_duplicates` for both `keep_id` and every `remove_id`) — one
function, one message, for the "no target scenario"/"not pending" check
every one of those needs.

**`approve_entries`/`reject_entries` both use `Connection.begin_nested()`
per entry, not a bare loop** — identical reasoning to `modules.entries.
service.reverse_entries_bulk`: one bad id in a bulk Approve/Reject
shouldn't take any other entry down with it, and `db.get_connection()`'s
one-transaction-per-request design means a bare loop would abort the
whole batch on the first error. A `SAVEPOINT` per entry gives each one
true independence instead."""
from datetime import date

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...domain.entry import parse_lines, parse_tags
from ...errors import pg_message
from . import repository as repo


def _validate_pending(conn: Connection, entry_id: str) -> dict:
    """Raises `ValueError` unless `entry_id` is a real, still-pending
    Staging entry; otherwise returns the joined row from `repository.
    staged_entry`, with `target_scenario_id` resolved to the ACTUAL
    scenario when neither producer named one. Ported from `_pending_
    staging_entry`, consolidated with `approve_staging_entries`'s own
    duplicate inline block — see this module's own docstring."""
    staged = repo.staged_entry(conn, entry_id)
    if not staged or not staged["is_staging"]:
        raise ValueError(f"#{entry_id}: not a pending staging entry")
    if staged["promoted_entry_id"] is not None:
        raise ValueError(f"#{entry_id}: already approved")
    target_scenario_id = staged["target_scenario_id"]
    if target_scenario_id is None:
        target_scenario_id = repo.actual_scenario_id(conn)
    if target_scenario_id is None:
        raise ValueError(f"#{entry_id}: no target scenario to approve into")
    return {**staged, "target_scenario_id": target_scenario_id}


def list_pending(conn: Connection, *, date_from: str = "", date_to: str = "", qtext: str = "",
                  tags: str = "", account: str = "", payee: str = "", amount_op: str = "",
                  amount_value: str = "", amount_value2: str = "", target_scenario: str = "") -> dict:
    """Filtered Staging listing, unpaginated — Staging is never large
    enough to need it. Each entry comes back with its own `lines`/`tags`
    nested directly under it, same "no reason to redo grouping the
    backend already did" reasoning `modules.entries.service.list_entries`'s own docstring
    gives for the identical choice there."""
    try:
        tag_list = parse_tags(tags) if tags else []
    except ValueError:
        tag_list = []
    where, params = repo.build_filter(
        date_from=date_from or None, date_to=date_to or None, qtext=qtext, tag_list=tag_list,
        account=account, payee=payee, amount_op=amount_op, amount_value=amount_value,
        amount_value2=amount_value2, target_scenario=target_scenario)
    rows = repo.list_pending_entries(conn, where, params)

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
    return {"entries": entries}


def approve_entry(conn: Connection, entry_id: str, user_id: int | None = None) -> str:
    """Posts one staged entry into its target scenario — ported from
    `approve_staging_entries`'s own per-id body. Returns the new,
    posted entry's id."""
    staged = _validate_pending(conn, entry_id)
    new_id = repo.insert_entry(
        conn, scenario_id=staged["target_scenario_id"], entry_date=staged["entry_date"],
        description=staged["description"], reference=staged["reference"],
        payee_id=staged["payee_id"], created_by_user_id=user_id)
    repo.copy_lines(conn, new_id, entry_id)
    repo.copy_tags(conn, new_id, entry_id)
    repo.mark_promoted(conn, entry_id, new_id)
    repo.check_deferred_constraints(conn)
    return new_id


def approve_entries(conn: Connection, entry_ids: list[str],
                     user_id: int | None = None) -> tuple[list[str], list[str]]:
    """Bulk sibling of `approve_entry` — ported from `approve_staging_
    entries`'s own loop, with the `SAVEPOINT`-per-entry adaptation this
    module's own docstring explains."""
    approved: list[str] = []
    errors: list[str] = []
    for eid in entry_ids:
        try:
            with conn.begin_nested():
                approved.append(approve_entry(conn, eid, user_id))
        except ValueError as e:
            errors.append(str(e))
        except SQLAlchemyError as e:
            errors.append(pg_message(e))
    return approved, errors


def get_edit_data(conn: Connection, entry_id: str) -> dict:
    """What the inline edit panel needs to fill itself in — ported from
    `staging_edit_data`, minus the `target_scenario`/`accounts` picker
    payloads (`repository.py`'s own docstring explains why: those are
    `modules/reference/` concerns, fetched separately by the frontend)."""
    staged = _validate_pending(conn, entry_id)
    lines = repo.lines_for_entries(conn, [entry_id])
    tag_names = [t["name"] for t in repo.tags_for_entries(conn, [entry_id])]
    return {
        "entry": {
            "id": staged["id"], "entry_date": staged["entry_date"],
            "description": staged["description"], "reference": staged["reference"] or "",
            "payee_id": staged["payee_id"],
        },
        "lines": lines, "tags": tag_names,
        "target_scenario_id": staged["target_scenario_id"],
    }


def save_edit(conn: Connection, entry_id: str, *, entry_date: date | None, description: str,
              reference: str | None, payee_id: int | None, tags: str, accounts: list[str],
              debits: list[str], credits: list[str], memos: list[str]) -> None:
    """Ported from `staging_edit_save`'s validation-then-replace body.
    Delete-then-reinsert for the lines (`repository.replace_lines`'s own
    docstring explains why that's the only shape available), then a full
    header `UPDATE` — both inside the caller's one open transaction, so
    the deferred balance/has-lines triggers only ever see the final,
    complete set at `check_deferred_constraints`'s forced check point,
    never the momentarily-empty state in between."""
    _validate_pending(conn, entry_id)
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

    repo.update_entry_header(conn, entry_id, entry_date=entry_date or date.today(),
                              description=description, reference=reference, payee_id=payee_id)
    repo.replace_lines(conn, entry_id, [
        {"account_id": found[ln["code"]], "amount": ln["amount"], "memo": ln["memo"]}
        for ln in lines])
    repo.sync_entry_tags(conn, entry_id, tag_names)
    repo.check_deferred_constraints(conn)


def reject_entry(conn: Connection, entry_id: str) -> None:
    """Permanently discards one pending entry. A real `DELETE`, not a
    reversal: nothing here was ever approved, so there's nothing to
    reverse, only a proposal to withdraw."""
    _validate_pending(conn, entry_id)
    repo.delete_lines_for_entry(conn, entry_id)
    repo.delete_entry(conn, entry_id)


def reject_entries(conn: Connection, entry_ids: list[str]) -> tuple[list[str], list[str]]:
    """Bulk sibling of `reject_entry` — `SAVEPOINT`-per-entry, same as
    `approve_entries`."""
    rejected: list[str] = []
    errors: list[str] = []
    for eid in entry_ids:
        try:
            with conn.begin_nested():
                reject_entry(conn, eid)
                rejected.append(eid)
        except ValueError as e:
            errors.append(str(e))
        except SQLAlchemyError as e:
            errors.append(pg_message(e))
    return rejected, errors


def find_duplicate_groups(conn: Connection) -> list[dict]:
    """Groups every pending-or-not staging-origin entry (see `repository.
    all_pending_entries_basic`'s own docstring on why "pending-or-not")
    by an exact fingerprint — same date, same `(account_id, amount)` leg
    set — ported from `_find_staging_duplicate_groups`. The matching
    rule, exactly the original ask's wording: "the same credit and debit
    accounts, with the same amounts, AND the date matches." A 2-leg
    entry and a 3-leg entry can never match regardless of what their
    first two legs look like, since a duplicate is "the same transaction
    posted twice," not "a similar one." """
    entries = repo.all_pending_entries_basic(conn)
    if not entries:
        return []
    ids = [e["id"] for e in entries]
    lines_by_entry: dict[str, list] = {}
    for ln in repo.lines_for_entries_signed(conn, ids):
        lines_by_entry.setdefault(ln["entry_id"], []).append(ln)
    tags_by_entry: dict[str, list] = {}
    for tg in repo.tags_for_entries(conn, ids):
        tags_by_entry.setdefault(tg["entry_id"], []).append(tg["name"])

    def flow_label(lines: list) -> str:
        # Mirrors the Dashboard's own "Salary Income -> Checking" flow
        # label — a section header names the transaction, not any one
        # entry's own description, since the whole point of grouping is
        # that every entry in it *is* the same transaction. Collapses to
        # "multiple" on either side for a 3+-leg group.
        credit_names = sorted({l["account_name"] for l in lines if l["amount"] < 0})
        debit_names = sorted({l["account_name"] for l in lines if l["amount"] > 0})
        credit_side = credit_names[0] if len(credit_names) == 1 else "multiple"
        debit_side = debit_names[0] if len(debit_names) == 1 else "multiple"
        return f"{credit_side} → {debit_side}"

    groups: dict[tuple, list] = {}
    for e in entries:
        lines = lines_by_entry.get(e["id"], [])
        fingerprint = (e["entry_date"], tuple(sorted((l["account_id"], l["amount"]) for l in lines)))
        e["lines"] = lines
        e["tags"] = tags_by_entry.get(e["id"], [])
        groups.setdefault(fingerprint, []).append(e)

    result = []
    for (entry_date, _legs), group_entries in groups.items():
        if len(group_entries) < 2:
            continue  # not a duplicate of anything -- the common case
        result.append({
            "label": f"{entry_date.isoformat()}: {flow_label(group_entries[0]['lines'])}",
            "entry_date": entry_date,
            "entries": group_entries,
        })
    result.sort(key=lambda g: g["entry_date"])
    return result


def merge_duplicates(conn: Connection, *, keep_id: str, remove_ids: list[str], description: str,
                      reference: str | None, payee_id: int | None, tags: str,
                      line_memos: dict[str, str]) -> None:
    """Collapses one duplicate group to a single survivor (`keep_id`) —
    ported from `merge_staging_duplicates`. Every `remove_id` is
    discarded outright (see `reject_entry`'s own docstring on why a
    delete, not a reversal); `keep_id` gets the description/reference/
    payee/tags typed into the merge popup, plus whatever per-line memo
    overrides `line_memos` names for lines it actually owns."""
    if not keep_id or not remove_ids:
        raise ValueError("Select at least two entries in one group to merge")
    _validate_pending(conn, keep_id)
    for rid in remove_ids:
        _validate_pending(conn, rid)
    description = (description or "").strip()
    if not description:
        raise ValueError("Description can't be empty")
    tag_names = parse_tags(tags)

    repo.update_entry_fields(conn, keep_id, description=description, reference=reference,
                              payee_id=payee_id)
    repo.sync_entry_tags(conn, keep_id, tag_names)
    for line_id in repo.line_ids_for_entry(conn, keep_id):
        memo_val = line_memos.get(str(line_id))
        if memo_val is not None:
            repo.update_line_memo(conn, line_id, memo_val.strip() or None)
    repo.delete_lines_for_entries(conn, remove_ids)
    repo.delete_entries(conn, remove_ids)
