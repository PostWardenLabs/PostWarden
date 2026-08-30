"""Both importers, and the shared Staging-landing step behind them.
Ported from `app/main.py`'s `_parse_csv_import`, `_stage_import_groups`,
`_parse_mapped_import_file`, `_transform_mapped_rows`, and the request-
handling bodies of `import_csv`/`import_mapped_preview`/`import_mapped_
commit`. Every function that touches the database takes a SQLAlchemy
`Connection` and reads/writes through `repository.py`, same convention
every prior module established.

**`stage_import_groups` is the one function both importers funnel
through** — ported from `_stage_import_groups`, which legacy's own
docstring already called out as "shared by both importers": one
`import_batches` row, then one `journal_entries` + its `journal_lines`
per group, regardless of which parser produced `groups`. Both `groups`
shapes (the raw double-entry CSV's, and the mapped single-entry CSV's
post-`transform_mapped_rows` output) agree on the same dict shape —
`entry_date`/`description`/`reference`/`payee_name`/`lines` (each line
`{code, amount, memo}`) — same as legacy.

**Amounts are `Decimal` throughout, not legacy's `float(d)`/`round(...,
2)`.** Same fix `domain.entry.parse_lines` (Phase 1.1) and `modules.
budget.service.save_budget_cell` (Phase 1.7) already applied to user-
typed money for the identical reason: every amount ends up in a
`NUMERIC(18,2)` column, so `float` was only ever a latent-imprecision
risk introduced on the way in, with no upside. `_parse_csv_import`'s own
`round(dv - cv, 2)` and `_transform_mapped_rows`'s own `round(amount, 2)`
both become `.quantize(Decimal("0.01"))` here.

**No CSRF check, no `created_by_user_id`/`imported_by_user_id`
attribution wired to a real user.** Same two documented gaps every prior
write module carries — both are `modules/auth/` (Phase 1.11) concerns.
Every import runs with `user_id=None` for now; `import_batches.imported_
by_user_id` is nullable for exactly this reason, same as `journal_
entries.created_by_user_id` (`db/schema.sql`'s own comment, already
noted in `modules/entries/repository.py`'s docstring).

**No scenario-picker payload anywhere in this module** — same "don't
reach into a module that doesn't exist yet" reasoning `repository.py`'s
own docstring gives for `recent_batches`. `import_csv`/`import_mapped`
both take `target_scenario_id` as a plain caller-supplied int, trusting
whatever the frontend's own (future, `modules/reference/`-backed) picker
sent — exactly as legacy's own form did, which never validated it beyond
the foreign key `import_batches.target_scenario_id` already enforces."""
import base64
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.engine import Connection

from . import repository as repo

IMPORT_REQUIRED_COLUMNS = ["Entry #", "Date", "Description", "Account code"]
IMPORT_MAX_ERRORS_SHOWN = 20

# ActualBudget-style single-entry export columns the mapped importer reads.
# See `_parse_mapped_import_file`'s legacy docstring: no built-in double
# entry, an Account column and a Category column instead, mapped into real
# double-entry postings by `transform_mapped_rows` below.
IMPORT_MAPPED_COLUMNS = ["Account", "Date", "Payee", "Notes", "Category", "Amount"]
IMPORT_MAPPED_NO_CATEGORY = ""  # the map key for blank/"(no category)" rows


def recent_batches(conn: Connection, limit: int = 10) -> list[dict]:
    """Thin pass-through to `repository.recent_batches` — kept here, not
    called directly from `router.py`, for the same "router calls service,
    service calls repository" convention every prior module's `router.py`
    follows."""
    return repo.recent_batches(conn, limit)


def parse_csv_import(conn: Connection, content: str) -> tuple[list[dict], list[str]]:
    """(groups, errors) — every group in `groups` already passed every
    check (a real account code, exactly one of debit/credit per line, and
    the whole entry nets to zero) and is ready to stage. `errors`
    describes every row/group that didn't, by original CSV row number,
    and never touches the database beyond the one account-code lookup.
    Ported from `_parse_csv_import`; see this module's own docstring on
    why amounts are `Decimal` here where legacy used `float`. The "Entry
    #"/"Scenario"/"Account name" columns an export produces are read only
    to group rows and are otherwise ignored — the id isn't reused, and
    the scenario a batch lands in comes from the import form, never
    trusted from inside the file itself."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["The file is empty"]
    missing = [c for c in IMPORT_REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}"]

    raw_groups: dict[str, list[tuple[int, dict]]] = {}
    order: list[str] = []
    errors = []
    for i, row in enumerate(reader, start=2):  # header is row 1
        key = (row.get("Entry #") or "").strip()
        if not key:
            errors.append(f"Row {i}: missing Entry #")
            continue
        if key not in raw_groups:
            raw_groups[key] = []
            order.append(key)
        raw_groups[key].append((i, row))

    codes = {(row.get("Account code") or "").strip()
             for rows in raw_groups.values() for _, row in rows}
    codes.discard("")
    found = repo.account_ids_by_code(conn, list(codes)) if codes else {}

    groups = []
    for key in order:
        rows = raw_groups[key]
        first_row_no, first = rows[0]
        lines, ok = [], True
        for row_no, row in rows:
            code = (row.get("Account code") or "").strip()
            if not code:
                errors.append(f"Row {row_no} (entry {key}): missing Account code")
                ok = False
                continue
            if code not in found:
                errors.append(f"Row {row_no} (entry {key}): unknown account code {code!r}")
                ok = False
                continue
            d, c = (row.get("Debit") or "").strip(), (row.get("Credit") or "").strip()
            try:
                dv = Decimal(d) if d else Decimal("0")
                cv = Decimal(c) if c else Decimal("0")
            except InvalidOperation:
                errors.append(f"Row {row_no} (entry {key}): Debit/Credit must be numeric")
                ok = False
                continue
            if dv < 0 or cv < 0 or (dv > 0) == (cv > 0):
                errors.append(f"Row {row_no} (entry {key}): enter exactly one positive Debit or Credit")
                ok = False
                continue
            lines.append({"code": code, "amount": (dv - cv).quantize(Decimal("0.01")),
                          "memo": (row.get("Memo") or "").strip() or None})
        if not ok:
            continue
        total = sum(ln["amount"] for ln in lines)
        if total != 0:
            errors.append(f"Entry {key} (row {first_row_no}): doesn't balance (off by {total:+.2f})")
            continue
        entry_date = (first.get("Date") or "").strip()
        try:
            date.fromisoformat(entry_date)
        except ValueError:
            errors.append(f"Entry {key} (row {first_row_no}): invalid Date {entry_date!r} — expected YYYY-MM-DD")
            continue
        description = (first.get("Description") or "").strip()
        if not description:
            errors.append(f"Entry {key} (row {first_row_no}): missing Description")
            continue
        groups.append({
            "entry_date": entry_date, "description": description,
            "reference": (first.get("Reference") or "").strip() or None,
            "payee_name": (first.get("Payee") or "").strip() or None,
            "lines": lines,
        })
    return groups, errors


def stage_import_groups(conn: Connection, groups: list[dict], filename: str,
                         target_scenario_id: int, user_id: int | None) -> int:
    """Shared by both importers — see this module's own docstring. Ported
    from `_stage_import_groups`. Returns the new batch id. Raises
    `ValueError` if there's no configured Staging scenario, same as
    legacy (`db/schema.sql`'s `uq_one_staging_scenario` means this can
    only happen on a database nobody has finished setting up).

    **One real deviation from a verbatim port**: legacy's own `INSERT`
    resolves each line's `account_id` via an inline `(SELECT id FROM
    accounts WHERE code = %s)` subquery, so an unknown code (impossible
    from `parse_csv_import`, whose groups are pre-validated, but *not*
    impossible from `import_mapped`, whose `account_map`/`category_map`
    values are caller-supplied and never checked against real accounts)
    silently resolves to `NULL` and only fails later on `journal_lines.
    account_id`'s own `NOT NULL` constraint — a working but unhelpfully
    generic error. This resolves every code across every group up front
    instead, the same explicit "unknown account code" check `modules.
    entries.service.create_entry` and `modules.staging.service.save_edit`
    already both do, so a bad mapping value fails with a clear message
    before any row is written, not a bare NOT NULL violation after."""
    staging_id = repo.staging_scenario_id(conn)
    if staging_id is None:
        raise ValueError("No Staging scenario configured")
    codes = {ln["code"] for g in groups for ln in g["lines"]}
    found = repo.account_ids_by_code(conn, list(codes))
    missing = codes - found.keys()
    if missing:
        raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

    batch_id = repo.insert_import_batch(
        conn, filename=filename, target_scenario_id=target_scenario_id,
        imported_by_user_id=user_id, row_count=len(groups))
    for g in groups:
        payee_id = repo.upsert_payee(conn, g["payee_name"]) if g["payee_name"] else None
        entry_id = repo.insert_staged_entry(
            conn, scenario_id=staging_id, entry_date=g["entry_date"], description=g["description"],
            reference=g["reference"], payee_id=payee_id, import_batch_id=batch_id)
        for n, ln in enumerate(g["lines"], start=1):
            repo.insert_line(conn, entry_id=entry_id, line_no=n, account_id=found[ln["code"]],
                              amount=ln["amount"], memo=ln["memo"])
    repo.check_deferred_constraints(conn)
    return batch_id


def import_csv(conn: Connection, *, content: str, filename: str, target_scenario_id: int,
                user_id: int | None = None) -> dict:
    """The plain double-entry CSV importer's full request body — ported
    from `import_csv`'s try block. Raises `ValueError` when there's
    nothing valid to stage at all (a missing-column file, or every group
    failing validation), same as legacy; a partial success (some groups
    good, some not) stages the good ones and reports the rest in
    `errors` instead of raising."""
    groups, errors = parse_csv_import(conn, content)
    if not groups:
        raise ValueError("; ".join(errors[:IMPORT_MAX_ERRORS_SHOWN]) or "No valid entries found in the file")
    batch_id = stage_import_groups(conn, groups, filename, target_scenario_id, user_id)
    return {"batch_id": batch_id, "staged_count": len(groups), "errors": errors}


def parse_mapped_file(content: str) -> tuple[list[dict], list[str]]:
    """(rows, errors). Unlike `parse_csv_import`, this never validates
    account codes or balances — there's no double entry yet at this
    point, just raw single-entry rows waiting on the mapping step. Pure —
    no database — ported from `_parse_mapped_import_file`."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["The file is empty"]
    missing = [c for c in IMPORT_MAPPED_COLUMNS if c not in reader.fieldnames]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)} — this importer "
                     f"expects an ActualBudget-style export (Account, Date, Payee, Notes, "
                     f"Category, Amount)"]
    rows = []
    for i, row in enumerate(reader, start=2):  # header is row 1
        rows.append({
            "row_no": i,
            "account": (row.get("Account") or "").strip(),
            "date": (row.get("Date") or "").strip(),
            "payee": (row.get("Payee") or "").strip(),
            "notes": (row.get("Notes") or "").strip(),
            "category": (row.get("Category") or "").strip(),
            "amount": (row.get("Amount") or "").strip(),
        })
    return rows, []


def preview_mapped(content: str) -> dict:
    """What the mapping step's picker lists need — ported from `import_
    mapped_preview`'s post-parse body (minus `postable`, a `modules/
    reference/` concern the frontend fetches separately, same reasoning
    every prior module applies). Raises `ValueError` on a bad file, same
    as legacy."""
    rows, errors = parse_mapped_file(content)
    if errors:
        raise ValueError("; ".join(errors))
    if not rows:
        raise ValueError("No rows found in the file")
    return {
        "row_count": len(rows),
        "accounts_found": sorted({r["account"] for r in rows if r["account"]}),
        "categories_found": sorted({r["category"] for r in rows if r["category"]}),
        "has_no_category_rows": any(not r["category"] for r in rows),
    }


def transform_mapped_rows(rows: list[dict], account_map: dict[str, str], category_map: dict[str, str],
                           flip_sign: bool) -> tuple[list[dict], list[str]]:
    """Applies the two mappings row by row, producing the same
    (groups, errors) shape `parse_csv_import` returns — every group
    already balanced by construction (two legs, one the negation of the
    other), so it can go straight into `stage_import_groups`. A zero-
    amount row (some exports include these for a pending/cleared marker
    row) is silently skipped, not an error — there's nothing to post.
    Pure — no database — ported from `_transform_mapped_rows`; see this
    module's own docstring on `Decimal` vs legacy's `float`."""
    groups, errors = [], []
    for r in rows:
        money_code = account_map.get(r["account"])
        if not money_code:
            errors.append(f"Row {r['row_no']}: no mapping chosen for account {r['account']!r}")
            continue
        cat_key = r["category"] or IMPORT_MAPPED_NO_CATEGORY
        other_code = category_map.get(cat_key)
        if not other_code:
            label = r["category"] or "(no category)"
            errors.append(f"Row {r['row_no']}: no mapping chosen for category {label!r}")
            continue
        try:
            amount = Decimal(r["amount"].replace(",", "")).quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append(f"Row {r['row_no']}: Amount {r['amount']!r} isn't numeric")
            continue
        if flip_sign:
            amount = -amount
        if amount == 0:
            continue
        try:
            entry_date = date.fromisoformat(r["date"])
        except ValueError:
            errors.append(f"Row {r['row_no']}: invalid Date {r['date']!r} — expected YYYY-MM-DD")
            continue
        memo = r["notes"] or None
        # Standard expense-tracker sign convention (negative = money out):
        # debit whichever side increases, credit whichever side decreases.
        # An expense (amount < 0) increases the category/expense account
        # and decreases the money account; income/a refund (amount > 0)
        # is the mirror image. Same "debit-positive" amount convention
        # journal_lines.amount already uses everywhere else in the app.
        if amount < 0:
            lines = [{"code": other_code, "amount": -amount, "memo": memo},
                     {"code": money_code, "amount": amount, "memo": memo}]
        else:
            lines = [{"code": money_code, "amount": amount, "memo": memo},
                     {"code": other_code, "amount": -amount, "memo": memo}]
        groups.append({
            "entry_date": entry_date.isoformat(),
            "description": r["payee"] or r["category"] or "Imported transaction",
            "reference": None, "payee_name": r["payee"] or None, "lines": lines,
        })
    return groups, errors


def import_mapped(conn: Connection, *, content: str, filename: str, target_scenario_id: int,
                   account_map: dict[str, str], category_map: dict[str, str], flip_sign: bool,
                   user_id: int | None = None) -> dict:
    """The mapped importer's commit step — ported from `import_mapped_
    commit`'s try block, minus the base64/hidden-form-field round-trip
    (see `router.py`'s own docstring on why the wire shape changed, not
    the behavior)."""
    rows, errors = parse_mapped_file(content)
    if errors:
        raise ValueError("; ".join(errors))
    groups, row_errors = transform_mapped_rows(rows, account_map, category_map, flip_sign)
    if not groups:
        raise ValueError("; ".join(row_errors[:IMPORT_MAX_ERRORS_SHOWN])
                         or "No valid entries produced — check the mapping")
    batch_id = stage_import_groups(conn, groups, filename, target_scenario_id, user_id)
    return {"batch_id": batch_id, "staged_count": len(groups), "errors": row_errors}


def decode_upload(raw: bytes) -> str:
    """`utf-8-sig` so an Excel-exported CSV's BOM doesn't end up glued to
    the first header name — ported from both importers' identical
    `raw.decode("utf-8-sig")` call, with legacy's own `UnicodeDecodeError`
    -> `ValueError` translation so a router only ever has one exception
    type to catch."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Could not read the file as UTF-8 text")


def encode_for_roundtrip(raw: bytes) -> str:
    """The preview step's file content, base64-encoded so it can travel
    to the frontend and back as plain JSON text for the commit step —
    same round-trip legacy's hidden `file_b64` form field performs, just
    JSON-shaped. See `router.py`'s own docstring."""
    return base64.b64encode(raw).decode("ascii")


def decode_roundtrip(b64: str) -> str:
    """The inverse of `encode_for_roundtrip`, then `decode_upload`'s same
    `utf-8-sig` handling — what `import_mapped`'s caller feeds it as
    `content`."""
    return decode_upload(base64.b64decode(b64))
