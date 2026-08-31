"""Both importers, and the shared Staging-landing step behind them.
Every function that touches the database takes a SQLAlchemy
`Connection` and reads/writes through `repository.py`, same convention
every prior module established.

**`stage_import_groups` is the one function both importers funnel
through**: one `import_batches` row, then one `journal_entries` + its
`journal_lines` per group, regardless of which parser produced
`groups`. Both `groups` shapes (the raw double-entry CSV's, and the
mapped single-entry CSV's post-`transform_mapped_rows` output) agree on
the same dict shape — `entry_date`/`description`/`reference`/
`payee_name`/`lines` (each line `{code, amount, memo}`).

**Amounts are `Decimal` throughout, never `float`.** Same fix
`domain.entry.parse_lines` and `modules.budget.service.save_budget_cell`
already apply to user-typed money for the identical reason: every
amount ends up in a `NUMERIC(18,2)` column, so `float` is only ever a
latent-imprecision risk introduced on the way in, with no upside.

**No CSRF check, no `created_by_user_id`/`imported_by_user_id`
attribution wired to a real user.** Same two documented gaps every prior
write module carries — both are `modules/auth/` concerns. Every import
runs with `user_id=None` for now; `import_batches.imported_by_user_id`
is nullable for exactly this reason, same as `journal_
entries.created_by_user_id` (`db/schema.sql`'s own comment, already
noted in `modules/entries/repository.py`'s docstring).

**No scenario-picker payload anywhere in this module** — same "don't
reach into a module that doesn't exist yet" reasoning `repository.py`'s
own docstring gives for `recent_batches`. `import_csv`/`import_mapped`
both take `target_scenario_id` as a plain caller-supplied int, trusting
whatever the frontend's own `modules/reference/`-backed picker sent —
the foreign key `import_batches.target_scenario_id` is what actually
enforces it's valid."""
import base64
import csv
import io
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.engine import Connection

from . import repository as repo

IMPORT_REQUIRED_COLUMNS = ["Entry #", "Date", "Description", "Account code"]
IMPORT_MAX_ERRORS_SHOWN = 20

# Step 1 of IMPORT_WIZARD.md's spine (§3) — Phase 2. A "dialect" is the
# handful of low-level, per-file text-formatting choices that sit below
# column mapping: which character separates fields, how many leading
# lines to skip before the real header, which character is the decimal
# point inside a number, which (if any) character groups thousands, and
# which of a small fixed set of date layouts the file's own date column
# uses. None of this is specific to *this* file's own column meanings —
# it's specific to *which spreadsheet program or bank* produced the
# export, which is exactly why it's sniffed once, up front, rather than
# folded into `IMPORT_MAPPED_FIELDS`' column-mapping step.
#
# Deliberately excludes encoding. `decode_upload`'s `utf-8-sig` already
# handles the one real-world case that matters here (a BOM'd Excel
# export); true multi-encoding detection (Latin-1/Windows-1252 exports)
# is out of scope until there's a second file format to justify the
# abstraction R7 calls for.
IMPORT_DEFAULT_DIALECT = {
    "delimiter": ",",
    "header_row": 0,           # how many leading lines to skip before the header
    "decimal_separator": ".",
    "thousands_separator": "",  # "" means "don't strip anything"
    "date_format": "iso",       # a key into _DATE_FORMAT_STRPTIME below
}
IMPORT_DELIMITERS = [
    {"key": ",", "label": "Comma ( , )"},
    {"key": ";", "label": "Semicolon ( ; )"},
    {"key": "\t", "label": "Tab"},
    {"key": "|", "label": "Pipe ( | )"},
]
IMPORT_DATE_FORMATS = [
    {"key": "iso", "label": "YYYY-MM-DD"},
    {"key": "us", "label": "MM/DD/YYYY"},
    {"key": "eu", "label": "DD/MM/YYYY"},
]
_DATE_FORMAT_STRPTIME = {"iso": "%Y-%m-%d", "us": "%m/%d/%Y", "eu": "%d/%m/%Y"}
_DATE_FORMAT_LABELS = {f["key"]: f["label"] for f in IMPORT_DATE_FORMATS}

# The mapped importer's own target fields — what a single-entry export's
# real columns (whatever they're actually called: "Memo", "Merchant",
# "Transaction Date", ActualBudget's own "Account"/"Payee"/etc., or
# anything else) get mapped *onto* by the wizard's column-mapping step,
# before any of `transform_mapped_rows`' Account/Category logic runs.
# Replaces the old `IMPORT_MAPPED_COLUMNS` exact-name requirement, which
# only ever worked because ActualBudget's own export happened to already
# use these literal header names — any other export needed a rename
# before it could be imported at all. `key` is the internal field name
# every downstream function (`parse_mapped_file` and on) still uses;
# `label` is what the mapping step's own picker shows, deliberately
# "Money Account"/"Category" rather than bare "Account" — the mapping
# step's whole job is picking *which* of the file's account-shaped
# columns is the money side versus the category side, and two options
# both labeled "Account" would defeat that. `required` gates preview/
# commit validation the same way the old exact-column-name check did:
# money account, date, and amount are the three fields a double-entry
# posting can't exist without; payee/description/memo/category are all
# optional, same as they always were (a blank Category row is exactly
# what `IMPORT_MAPPED_NO_CATEGORY` below already exists to handle).
#
# `description` and `memo` are deliberately separate targets, not one
# "Notes" field mapped onto two different downstream uses. The original
# ask mapped a file's Notes column to the entry description; the shipped
# code instead used Payee for that (falling back to Category, then a
# fixed string) and Notes became the *line* memo — both are legitimate,
# but leaving the choice implicit inside `transform_mapped_rows` meant a
# user had no way to see or change it. `description` lets a user map a
# column straight to the entry description when they have one; leaving
# it unmapped keeps the same payee/category/fallback chain
# `transform_mapped_rows` always used (documented there, and in the
# mapping step's own UI, rather than only in this comment).
IMPORT_MAPPED_FIELDS = [
    {"key": "account", "label": "Money Account", "required": True},
    {"key": "date", "label": "Entry Date", "required": True},
    {"key": "amount", "label": "Amount", "required": True},
    {"key": "payee", "label": "Payee", "required": False},
    {"key": "description", "label": "Entry Description", "required": False},
    {"key": "memo", "label": "Line Memo", "required": False},
    {"key": "category", "label": "Category", "required": False},
]
IMPORT_MAPPED_NO_CATEGORY = ""  # the map key for blank/"(no category)" rows

_DECIMAL_COMMA_STRICT = re.compile(r"^-?\d{1,3}(\.\d{3})+,\d{2}$")   # 1.234,56
_DECIMAL_DOT_STRICT = re.compile(r"^-?\d{1,3}(,\d{3})+\.\d{2}$")     # 1,234.56
_DECIMAL_COMMA_WEAK = re.compile(r"^-?\d+,\d{2}$")                   # 12,50 — decimal-comma, no thousands
_DECIMAL_DOT_WEAK = re.compile(r"^-?\d+\.\d{2}$")                    # 12.50
_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def resolve_dialect(overrides: dict | None) -> dict:
    """Fills in `IMPORT_DEFAULT_DIALECT` for any key an `overrides` dict
    (from the wire, where every field is optional — a client that never
    touched the dialect panel sends `{}`) doesn't set. Every
    dialect-consuming function below takes a fully-populated dict, never
    a partial one — this is the one place that gets to assume that, so
    nothing downstream needs its own `.get(key, fallback)` guard."""
    return {**IMPORT_DEFAULT_DIALECT, **(overrides or {})}


def sniff_dialect(content: str) -> dict:
    """Best-guess dialect for a file the column-mapping step hasn't seen
    yet (IMPORT_WIZARD.md §3 step 1) — delimiter, how many leading lines
    to skip before the header, and the decimal/thousands separator and
    date format used inside the data cells themselves. Pure string
    sniffing with no column semantics at all (there's no `column_map`
    yet at this point in the wizard) — it looks at every cell across a
    sample of rows and votes, rather than assuming any one column is the
    Amount or the Date.

    Never raises for a merely-odd file — this is a *guess*, always
    editable in the dialect panel (R1); only a genuinely empty file is
    an error, same contract `sniff_mapped_columns` already has."""
    lines = content.splitlines()
    if not lines:
        raise ValueError("The file is empty")

    delimiter = _sniff_delimiter(lines)
    header_row = _sniff_header_row(lines[:10], delimiter)
    body_lines = lines[header_row + 1:header_row + 20]
    decimal_separator, thousands_separator = _sniff_decimal_style(body_lines, delimiter)
    date_format = _sniff_date_format(body_lines, delimiter)

    return {
        "delimiter": delimiter,
        "header_row": header_row,
        "decimal_separator": decimal_separator,
        "thousands_separator": thousands_separator,
        "date_format": date_format,
    }


def _sniff_delimiter(lines: list[str]) -> str:
    """`csv.Sniffer` reads a whole sample as one candidate table, and a
    genuinely blank line or a junk line above the real header (a title,
    an export timestamp) is exactly the kind of thing that makes it give
    up entirely (`csv.Error: Could not determine delimiter`) rather than
    fall back to a wrong-but-plausible guess — a blank line in the
    sample was enough to break it even on an otherwise unambiguous
    semicolon-delimited file. So: strip blank lines (they carry no
    delimiter evidence either way, and `_sniff_header_row` below still
    sees them fine — it works from the un-stripped `lines`), then retry
    from progressively later starting points, since the most common
    real cause of a failed sniff is one or more junk lines still sitting
    above the header in the sample. Falls back to comma only once every
    starting point has been tried and none worked."""
    non_blank = [line for line in lines[:20] if line.strip()]
    for start in range(len(non_blank)):
        sample = "\n".join(non_blank[start:start + 20])
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            continue
    return ","


def _sniff_header_row(lines: list[str], delimiter: str) -> int:
    """How many leading lines to skip before the real header — handles a
    file with a title line, a blank line, or an export timestamp above
    the actual table (some bank exports do this), rather than failing
    outright once the mapping step can't find any of its target fields
    among what it thinks are the column names. Heuristic: the header is
    the first line whose field count matches the mode among the next few
    lines — a junk line above it usually has a different field count
    (often 1, for a title or a blank line)."""
    counts = [len(line.split(delimiter)) for line in lines]
    if not counts:
        return 0
    body_counts = counts[1:] or counts
    mode = Counter(body_counts).most_common(1)[0][0]
    for i, c in enumerate(counts):
        if c == mode and c > 1:
            return i
    return 0


def _sniff_decimal_style(lines: list[str], delimiter: str) -> tuple[str, str]:
    """Votes across every cell in a sample of data rows, not just one
    presumed-Amount column — a strict match (`1.234,56`, with a full
    thousands group) counts double over a weak one (`12,50`, which reads
    the same whether or not there's a thousands separator in play) since
    it's unambiguous evidence, and a thousands separator is only ever
    reported once a strict match actually demonstrated one — a weak
    match alone isn't enough to claim there's a grouping character at
    all, only which side of the number the decimal fraction is on."""
    comma_votes = dot_votes = 0
    saw_comma_thousands = saw_dot_thousands = False
    for line in lines:
        for cell in line.split(delimiter):
            cell = cell.strip()
            if _DECIMAL_COMMA_STRICT.match(cell):
                comma_votes += 2
                saw_dot_thousands = True
            elif _DECIMAL_DOT_STRICT.match(cell):
                dot_votes += 2
                saw_comma_thousands = True
            elif _DECIMAL_COMMA_WEAK.match(cell):
                comma_votes += 1
            elif _DECIMAL_DOT_WEAK.match(cell):
                dot_votes += 1
    if comma_votes > dot_votes:
        return ",", ("." if saw_dot_thousands else "")
    return ".", ("," if saw_comma_thousands else "")


def _sniff_date_format(lines: list[str], delimiter: str) -> str:
    """Votes across every cell that looks date-shaped. `DD/MM/YYYY` and
    `MM/DD/YYYY` are only distinguishable when a component is over 12 —
    genuinely ambiguous otherwise, so ambiguous evidence never outvotes
    real evidence for the other, and the fallback when nothing at all
    matches is `iso`, the same format this importer only ever supported
    before this function existed (a guess that changes nothing for a
    file that gives no evidence either way)."""
    us_votes = eu_votes = iso_votes = 0
    for line in lines:
        for cell in line.split(delimiter):
            cell = cell.strip()
            if _DATE_ISO_RE.match(cell):
                iso_votes += 1
                continue
            m = _DATE_SLASH_RE.match(cell)
            if not m:
                continue
            first, second = int(m.group(1)), int(m.group(2))
            if first > 12:
                eu_votes += 1
            elif second > 12:
                us_votes += 1
    if iso_votes and iso_votes >= max(us_votes, eu_votes):
        return "iso"
    if eu_votes > us_votes:
        return "eu"
    if us_votes > 0:
        return "us"
    return "iso"


def _dict_reader(content: str, dialect: dict) -> csv.DictReader:
    """The one place `csv.DictReader` gets constructed — every row-reading
    function below (`parse_rows`, `sniff_mapped_columns`, `parse_mapped_
    file`, `parse_csv_import`) goes through this rather than building its
    own, so `dialect['delimiter']`/`dialect['header_row']` are honored
    everywhere consistently and a future second file format (R7) only
    has to plug in here. Private, not `parse_rows`, because a caller
    that needs `.fieldnames` without first exhausting the rows (`sniff_
    mapped_columns`, `parse_mapped_file`) still needs the reader object
    itself, not the plain list `parse_rows` hands back."""
    lines = content.splitlines()[dialect.get("header_row", 0):]
    return csv.DictReader(io.StringIO("\n".join(lines)), delimiter=dialect.get("delimiter", ","))


def parse_rows(content: str, dialect: dict) -> list[dict]:
    """`_dict_reader` above, fully consumed into plain `dict`s — the
    entry point for a caller that just wants every row and doesn't need
    the reader itself. Raises `ValueError` on a file with no header row
    to find (empty, or `header_row` skips past the whole file)."""
    reader = _dict_reader(content, dialect)
    if not reader.fieldnames:
        raise ValueError("The file is empty")
    return [dict(row) for row in reader]


def parse_amount(raw: str, dialect: dict) -> Decimal:
    """A dialect-aware replacement for the old inline
    `Decimal(r["amount"].replace(",", ""))` — strips the thousands
    separator (if the dialect names one), then normalizes whatever the
    dialect's own decimal separator is to `.` before handing off to
    `Decimal`. Raises `decimal.InvalidOperation` on anything that still
    isn't numeric, same as bare `Decimal(...)` always did — every caller
    already catches that."""
    text = raw.strip()
    thousands = dialect.get("thousands_separator", "")
    decimal_sep = dialect.get("decimal_separator", ".")
    if thousands:
        text = text.replace(thousands, "")
    if decimal_sep != ".":
        text = text.replace(decimal_sep, ".")
    return Decimal(text)


def parse_date(raw: str, dialect: dict) -> date:
    """A dialect-aware replacement for the old ISO-only
    `date.fromisoformat`. Raises `ValueError` on anything that doesn't
    match the dialect's own `date_format`, same as `date.fromisoformat`
    always did for a non-ISO string."""
    fmt = _DATE_FORMAT_STRPTIME.get(dialect.get("date_format", "iso"), "%Y-%m-%d")
    return datetime.strptime(raw.strip(), fmt).date()


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
    The "Entry #"/"Scenario"/"Account name" columns an export produces are read only
    to group rows and are otherwise ignored — the id isn't reused, and
    the scenario a batch lands in comes from the import form, never
    trusted from inside the file itself. Reads through `_dict_reader`
    with the plain importer's own fixed dialect — this importer has no
    dialect-panel UI of its own (that's the mapped importer's Phase 2,
    IMPORT_WIZARD.md §7), but sharing the one row-reading entry point is
    real R7 groundwork at zero behavior cost: same comma delimiter, same
    header-on-row-1 assumption this always had."""
    reader = _dict_reader(content, IMPORT_DEFAULT_DIALECT)
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
    """Shared by both importers — see this module's own docstring.
    Returns the new batch id. Raises `ValueError` if there's no
    configured Staging scenario (`db/schema.sql`'s `uq_one_staging_
    scenario` means this can only happen on a database nobody has
    finished setting up).

    **Every account code across every group is resolved up front,
    before any row is written.** An unknown code is impossible from
    `parse_csv_import`, whose groups are pre-validated, but *not*
    impossible from `import_mapped`, whose `account_map`/`category_map`
    values are caller-supplied and never checked against real accounts —
    resolving up front means a bad mapping value fails with a clear
    message, the same explicit "unknown account code" check `modules.
    entries.service.create_entry` and `modules.staging.service.save_edit`
    already both do, rather than surfacing later as a bare `journal_
    lines.account_id` `NOT NULL` violation."""
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
    """The plain double-entry CSV importer's full request body. Raises
    `ValueError` when there's nothing valid to stage at all (a
    missing-column file, or every group failing validation); a partial
    success (some groups good, some not) stages the good ones and
    reports the rest in `errors` instead of raising."""
    groups, errors = parse_csv_import(conn, content)
    if not groups:
        raise ValueError("; ".join(errors[:IMPORT_MAX_ERRORS_SHOWN]) or "No valid entries found in the file")
    batch_id = stage_import_groups(conn, groups, filename, target_scenario_id, user_id)
    return {"batch_id": batch_id, "staged_count": len(groups), "errors": errors}


def sniff_mapped_columns(content: str, dialect: dict = IMPORT_DEFAULT_DIALECT, sample_size: int = 5) -> dict:
    """What the mapping step's own picker needs before any target field
    can be chosen: the file's real column names, in file order (so the
    picker's dropdowns read the same left-to-right order the user's own
    file already has), plus a few real sample rows so a column can be
    matched by looking at its actual data, not just guessing from a
    header like "Memo" or "Desc". `dialect` — a full dict, see `resolve_
    dialect` — decides where the header row actually is and what splits
    a line into cells; pass the file's own sniffed (or user-edited)
    dialect once one exists, the default only for a caller (tests, a
    first pre-dialect look) that doesn't have one yet. Pure — no
    database. Raises `ValueError` on an empty file, same contract every
    other parse-step function in this module already has."""
    reader = _dict_reader(content, dialect)
    if not reader.fieldnames:
        raise ValueError("The file is empty")
    columns = list(reader.fieldnames)
    sample_rows = []
    for row in reader:
        sample_rows.append({c: (row.get(c) or "") for c in columns})
        if len(sample_rows) >= sample_size:
            break
    return {"columns": columns, "sample_rows": sample_rows}


def parse_mapped_file(content: str, column_map: dict[str, str],
                       dialect: dict = IMPORT_DEFAULT_DIALECT) -> tuple[list[dict], list[str]]:
    """(rows, errors). `column_map` is target-field-key -> the file's own
    column name for it (`IMPORT_MAPPED_FIELDS`' `key`s — "account",
    "date", ... — gathered by the mapping step, `sniff_mapped_columns`
    above), an empty/missing value meaning "not mapped." `dialect`
    decides the header row and the field delimiter, same as `sniff_
    mapped_columns` — row numbers in the returned rows (and in any
    error message) count from the file's own real line numbers, so they
    still make sense to a user looking at their own file even when
    `header_row` skipped a junk line or two above it. Unlike
    `parse_csv_import`, this never validates account codes or balances —
    there's no double entry yet at this point, just raw single-entry rows
    waiting on the review step's Account/Category mapping. Pure — no
    database.

    This shape is single-valued per target by construction (a `dict` key
    holds one value), which is exactly right for how this function reads
    a row but means it can never see "two file columns both claiming the
    Amount target" — whichever column the frontend's own column->target
    state happened to serialize last is the only one that survives the
    inversion into this shape, with no trace of the other. That's why
    that check lives in `ImportMappedPanel.tsx`, at the point where the
    raw per-column choices still exist, not here."""
    reader = _dict_reader(content, dialect)
    if not reader.fieldnames:
        return [], ["The file is empty"]
    missing_required = [f["label"] for f in IMPORT_MAPPED_FIELDS
                         if f["required"] and not column_map.get(f["key"])]
    if missing_required:
        return [], [f"Choose a column for: {', '.join(missing_required)}"]
    mapped_columns = {col for col in column_map.values() if col}
    unknown = mapped_columns - set(reader.fieldnames)
    if unknown:
        return [], [f"Mapped column(s) not found in the file: {', '.join(sorted(unknown))}"]

    def get(row: dict, key: str) -> str:
        col = column_map.get(key)
        return (row.get(col) or "").strip() if col else ""

    rows = []
    start = dialect.get("header_row", 0) + 2  # the header itself is one line past whatever got skipped
    for i, row in enumerate(reader, start=start):
        rows.append({
            "row_no": i,
            "account": get(row, "account"),
            "date": get(row, "date"),
            "payee": get(row, "payee"),
            "description": get(row, "description"),
            "memo": get(row, "memo"),
            "category": get(row, "category"),
            "amount": get(row, "amount"),
        })
    return rows, []


def preview_mapped(content: str, column_map: dict[str, str], dialect: dict = IMPORT_DEFAULT_DIALECT) -> dict:
    """What the review step's picker lists need — `postable` is left
    out, a `modules/reference/` concern the frontend fetches separately,
    same reasoning every prior module applies. Raises `ValueError` on a
    bad file or an incomplete `column_map`."""
    rows, errors = parse_mapped_file(content, column_map, dialect)
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
                           flip_sign: bool, dialect: dict = IMPORT_DEFAULT_DIALECT) -> tuple[list[dict], list[str]]:
    """Applies the two mappings row by row, producing the same
    (groups, errors) shape `parse_csv_import` returns — every group
    already balanced by construction (two legs, one the negation of the
    other), so it can go straight into `stage_import_groups`. A zero-
    amount row (some exports include these for a pending/cleared marker
    row) is silently skipped, not an error — there's nothing to post.
    Pure — no database — see this module's own docstring on why amounts
    stay `Decimal` throughout.

    `dialect`'s `decimal_separator`/`thousands_separator`/`date_format`
    drive `parse_amount`/`parse_date` here — this is the only place in
    the mapped importer's pipeline that actually reads a raw Amount or
    Date string as a number/date rather than a plain mapped string, so
    it's the only place those three dialect fields matter at all."""
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
            amount = parse_amount(r["amount"], dialect).quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append(f"Row {r['row_no']}: Amount {r['amount']!r} isn't numeric")
            continue
        if flip_sign:
            amount = -amount
        if amount == 0:
            continue
        try:
            entry_date = parse_date(r["date"], dialect)
        except ValueError:
            date_label = _DATE_FORMAT_LABELS.get(dialect.get("date_format", "iso"), "YYYY-MM-DD")
            errors.append(f"Row {r['row_no']}: invalid Date {r['date']!r} — expected {date_label}")
            continue
        memo = r["memo"] or None
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
        # Explicit fallback chain (§2.1 of IMPORT_WIZARD.md): an
        # `description`-mapped column wins outright when present; when
        # nothing is mapped there, the entry description falls back to
        # the payee, then the category, then a fixed placeholder — same
        # chain this always used, just no longer buried unlabeled inside
        # this one line.
        groups.append({
            "entry_date": entry_date.isoformat(),
            "description": r["description"] or r["payee"] or r["category"] or "Imported transaction",
            "reference": None, "payee_name": r["payee"] or None, "lines": lines,
        })
    return groups, errors


def import_mapped(conn: Connection, *, content: str, filename: str, target_scenario_id: int,
                   column_map: dict[str, str], account_map: dict[str, str], category_map: dict[str, str],
                   flip_sign: bool, dialect: dict = IMPORT_DEFAULT_DIALECT, user_id: int | None = None) -> dict:
    """The mapped importer's commit step — ported from `import_mapped_
    commit`'s try block, minus the base64/hidden-form-field round-trip
    (see `router.py`'s own docstring on why the wire shape changed, not
    the behavior). `column_map` is re-applied here rather than trusted
    from the preview step's own response, same "never trust caller-
    supplied structure without re-deriving it" reasoning `stage_import_
    groups`' own account-code re-resolution already documents. `dialect`
    gets the same treatment for the same reason."""
    rows, errors = parse_mapped_file(content, column_map, dialect)
    if errors:
        raise ValueError("; ".join(errors))
    groups, row_errors = transform_mapped_rows(rows, account_map, category_map, flip_sign, dialect)
    if not groups:
        raise ValueError("; ".join(row_errors[:IMPORT_MAX_ERRORS_SHOWN])
                         or "No valid entries produced — check the mapping")
    batch_id = stage_import_groups(conn, groups, filename, target_scenario_id, user_id)
    return {"batch_id": batch_id, "staged_count": len(groups), "errors": row_errors}


def decode_upload(raw: bytes) -> str:
    """`utf-8-sig` so an Excel-exported CSV's BOM doesn't end up glued to
    the first header name — shared by both importers. Translates a
    `UnicodeDecodeError` to `ValueError` so a router only ever has one
    exception type to catch."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Could not read the file as UTF-8 text")


def encode_for_roundtrip(raw: bytes) -> str:
    """The preview step's file content, base64-encoded so it can travel
    to the frontend and back as plain JSON text for the commit step. See
    `router.py`'s own docstring."""
    return base64.b64encode(raw).decode("ascii")


def decode_roundtrip(b64: str) -> str:
    """The inverse of `encode_for_roundtrip`, then `decode_upload`'s same
    `utf-8-sig` handling — what `import_mapped`'s caller feeds it as
    `content`."""
    return decode_upload(base64.b64decode(b64))
