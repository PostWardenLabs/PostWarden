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

# Step 2 of IMPORT_WIZARD.md's spine (§3) — Phase 4. "Shape" is the
# structural difference between "one row = one entry, one signed Amount
# column" (what the mapped importer has only ever supported) and "several
# rows share a key and combine into one entry, Debit/Credit instead of one
# signed Amount" (what the plain importer's fixed CSV format hardcoded).
# Making it a wizard setting, sniffed like `dialect` and re-editable, is
# what lets one pipeline (`parse_file`/`transform_rows`, IMPORT_WIZARD.md
# §7 Phase 4 item 3) produce both of today's importers' behavior as two
# configurations of the same code, rather than two separate functions.
#
# Deliberately just these two axes, not a fully general "how many legs can
# one file row express" question — a file row (in the "one" shape) always
# expresses exactly two legs (the money account and one "other" account);
# an arbitrary N-way split expressed by a *single* row (extra Split_Amount-
# style columns, R9) is explicitly out of scope here, same as it's out of
# scope everywhere else in this roadmap until R9 itself is scheduled.
IMPORT_DEFAULT_SHAPE = {
    "rows_per_entry": "one",        # "one" | "grouped"
    "group_key_column": None,       # a file column name; only meaningful when "grouped"
    "amount_style": "signed",       # "signed" | "debit_credit"
}
# Name fragments that make a column plausible as a grouping key — "Entry
# #", "Entry Number", "Transaction ID", "Txn Ref" and similar all match on
# at least one of these. Deliberately permissive (a false-positive sniff
# costs nothing, since R1 means it's always shown and always editable) but
# still restricted to *some* id-shaped hint — an arbitrary column that
# merely happens to repeat a value in the sample (a Category column, say)
# shouldn't be sniffed as a grouping key just because `_sniff_group_key_
# column` also requires repeated values as corroborating evidence.
_GROUP_KEY_NAME_HINTS = ("entry", "transaction", "txn", "id", "ref", "#")

# Step 4's per-column property (IMPORT_WIZARD.md §7 Phase 4 item 2): does a
# `lookup_capable` column (see `target_fields_for_shape`) already hold a
# real account code (the plain importer's historical `Account code`
# column), or a label that needs a lookup table built in the review step
# (the mapped importer's historical `Account`/`Category` columns)? This is
# the property that lets one `transform_rows` produce both importers'
# existing behavior as configuration rather than as two code paths.
# Default is `"label"` — the safer assumption when a caller (an old test,
# a not-yet-updated client) doesn't set it at all, since treating an
# unrecognized value as a code that needs no lookup would silently post to
# whatever raw text happened to be in the file.
IMPORT_COLUMN_KIND_CODE = "code"
IMPORT_COLUMN_KIND_LABEL = "label"
IMPORT_DEFAULT_COLUMN_KIND = IMPORT_COLUMN_KIND_LABEL
IMPORT_NO_VALUE_KEY = ""  # the value-map key for a blank/unset lookup-column cell

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


def sniff_shape(columns: list[str], sample_rows: list[dict]) -> dict:
    """Best-guess `shape` (IMPORT_WIZARD.md §7 Phase 4 item 1) from the
    same `columns`/`sample_rows` `sniff_mapped_columns` already produces —
    called right alongside it, not as a separate parse pass. Pure, never
    raises (R1: always a guess, always editable in the wizard's own shape
    panel); an empty or ambiguous file just falls back to `IMPORT_DEFAULT_
    SHAPE`'s values for whichever half it found no evidence for.

    `amount_style`: a case-insensitive `Debit`+`Credit` column pair is
    strong, unambiguous evidence (`_sniff_decimal_style`-style voting
    would be overkill here — either both columns exist by name or they
    don't) — `"debit_credit"` if both are present, `"signed"` otherwise.

    `rows_per_entry`: delegates to `_sniff_group_key_column` below, which
    requires *both* an id-shaped column name and actually-repeated values
    in the sample — either alone is too weak a signal on its own (see that
    function's own docstring)."""
    lower = {c.strip().lower(): c for c in columns}
    debit_col, credit_col = lower.get("debit"), lower.get("credit")
    amount_style = "debit_credit" if debit_col and credit_col else "signed"

    group_key_column = _sniff_group_key_column(columns, sample_rows)
    rows_per_entry = "grouped" if group_key_column else "one"

    return {
        "rows_per_entry": rows_per_entry,
        "group_key_column": group_key_column,
        "amount_style": amount_style,
    }


def _sniff_group_key_column(columns: list[str], sample_rows: list[dict]) -> str | None:
    """A column is a plausible grouping key only when *both* its name
    looks id-shaped (`_GROUP_KEY_NAME_HINTS`) *and* the sample actually
    shows a repeated value — name alone would false-positive on a column
    like "Transaction Type" that never repeats meaningfully-groupably;
    repetition alone would false-positive on any low-cardinality column
    (Category, Cleared) that isn't a grouping key at all. First matching
    column in file order wins; `None` (→ `rows_per_entry: "one"`) when
    nothing qualifies."""
    candidates = [c for c in columns if any(hint in c.strip().lower() for hint in _GROUP_KEY_NAME_HINTS)]
    for c in candidates:
        values = [(row.get(c) or "").strip() for row in sample_rows]
        values = [v for v in values if v]
        if len(values) > 1 and len(set(values)) < len(values):
            return c
    return None


def target_fields_for_shape(shape: dict) -> list[dict]:
    """Replaces the old fixed `IMPORT_MAPPED_FIELDS` constant as the sole
    source of what the mapping step's own picker offers. The mapped
    importer's file only ever had one shape (`rows_per_entry: "one"`,
    `amount_style: "signed"`), so a fixed list was exactly right for it;
    now that `shape` is itself a wizard setting, the *available* target
    fields are a function of it. Each entry is `{key, label, required,
    lookup_capable}` — `lookup_capable` is new (Phase 4 item 2): only a
    `lookup_capable` target can carry a `column_kinds` entry (`"code"` vs
    `"label"`, see `parse_file`/`transform_rows`) at all, since `date`/
    `amount`/`debit`/`credit`/`group_key`/etc. never have an
    account-shaped value to resolve.

    `rows_per_entry == "one"`: unchanged from the old `IMPORT_MAPPED_
    FIELDS` list when `amount_style == "signed"` — money account
    (required, lookup_capable), entry date (required), amount (required),
    payee/entry description/line memo (optional), category (optional,
    lookup_capable — the "other leg"). `amount_style == "debit_credit"`
    swaps the single `amount` target for `debit`+`credit`, both required
    — the same one-row-is-one-entry shape, just expressing its net as two
    columns instead of one signed one.

    `rows_per_entry == "grouped"`: a `group_key` target appears (required,
    never `lookup_capable` — its value only groups rows into one entry,
    it's never a leg's own account), and `account`/`date` become per-row
    requirements. `description` stays required, matching `parse_csv_
    import`'s historical `IMPORT_REQUIRED_COLUMNS`; `reference`/`payee`/
    `memo` stay optional. No `category` target — every row in a group
    already names its own leg's account directly via `account`, so
    there's no separate "other leg" column the way the one-row shape
    needs one (an entry with more than two legs is however many rows
    share one `group_key`, not more mapped columns)."""
    amount_style = shape.get("amount_style", "signed")
    amount_fields = (
        [{"key": "amount", "label": "Amount", "required": True, "lookup_capable": False}]
        if amount_style != "debit_credit" else
        [{"key": "debit", "label": "Debit", "required": True, "lookup_capable": False},
         {"key": "credit", "label": "Credit", "required": True, "lookup_capable": False}]
    )
    if shape.get("rows_per_entry") == "grouped":
        return [
            {"key": "group_key", "label": "Entry Group", "required": True, "lookup_capable": False},
            {"key": "date", "label": "Entry Date", "required": True, "lookup_capable": False},
            {"key": "account", "label": "Account", "required": True, "lookup_capable": True},
            *amount_fields,
            {"key": "description", "label": "Entry Description", "required": True, "lookup_capable": False},
            {"key": "reference", "label": "Reference", "required": False, "lookup_capable": False},
            {"key": "payee", "label": "Payee", "required": False, "lookup_capable": False},
            {"key": "memo", "label": "Line Memo", "required": False, "lookup_capable": False},
        ]
    return [
        {"key": "account", "label": "Money Account", "required": True, "lookup_capable": True},
        {"key": "date", "label": "Entry Date", "required": True, "lookup_capable": False},
        *amount_fields,
        {"key": "payee", "label": "Payee", "required": False, "lookup_capable": False},
        {"key": "description", "label": "Entry Description", "required": False, "lookup_capable": False},
        {"key": "memo", "label": "Line Memo", "required": False, "lookup_capable": False},
        {"key": "category", "label": "Category", "required": False, "lookup_capable": True},
    ]


def parse_file(content: str, shape: dict, column_map: dict[str, str],
                dialect: dict = IMPORT_DEFAULT_DIALECT) -> tuple[list[dict], list[str]]:
    """(rows, errors) — collapses `parse_csv_import` and `parse_mapped_
    file` into one function (IMPORT_WIZARD.md §7 Phase 4 item 3):
    `shape` decides which target fields exist at all (`target_fields_
    for_shape`), `column_map` decides which of the file's own columns
    fills each one, same target-field-key -> file-column-name shape
    `parse_mapped_file`'s `column_map` always had. Extraction only — no
    grouping (a `"grouped"` shape's rows aren't combined into entries
    here, that's `transform_rows`' job), no account-code or balance
    validation, same "pure single-entry-row extraction" job `parse_
    mapped_file` always had, now generalized to whatever `target_fields_
    for_shape(shape)` says the row-level fields are. `errors` stays flat
    `list[str]`, structural only (missing/unknown columns) — never
    per-row, same contract `parse_mapped_file` already has. Pure — no
    database (R12)."""
    reader = _dict_reader(content, dialect)
    if not reader.fieldnames:
        return [], ["The file is empty"]
    fields = target_fields_for_shape(shape)
    missing_required = [f["label"] for f in fields if f["required"] and not column_map.get(f["key"])]
    if missing_required:
        return [], [f"Choose a column for: {', '.join(missing_required)}"]
    mapped_columns = {col for col in column_map.values() if col}
    unknown = mapped_columns - set(reader.fieldnames)
    if unknown:
        return [], [f"Mapped column(s) not found in the file: {', '.join(sorted(unknown))}"]

    def get(row: dict, key: str) -> str:
        col = column_map.get(key)
        return (row.get(col) or "").strip() if col else ""

    keys = [f["key"] for f in fields]
    rows = []
    start = dialect.get("header_row", 0) + 2  # the header itself is one line past whatever got skipped
    for i, row in enumerate(reader, start=start):
        rows.append({"row_no": i, **{key: get(row, key) for key in keys}})
    return rows, []


def _resolve_leg_account(field_label: str, raw: str, kind: str, value_map: dict[str, str],
                          known_codes: set[str] | None) -> tuple[str | None, str | None]:
    """Resolves one lookup-capable column's raw row value to a real
    account code, per its own `column_kinds` entry (`IMPORT_DEFAULT_
    COLUMN_KIND` — `"label"` — when unset). Returns `(code, None)` on
    success, `(None, message)` on failure — never raises, since a
    resolution failure is a per-row `transform_rows` error, not a
    structural one.

    A `"code"`-kind column trusts `raw` verbatim as the real account
    code, *unless* the caller supplied `known_codes` (a real set of
    codes that exist in the ledger) and `raw` isn't in it — restoring the
    same per-row "unknown account code" diagnostic `parse_csv_import`
    used to give directly (it had a `Connection` in hand; `transform_
    rows` deliberately doesn't — see its own docstring). `known_codes is
    None` (every pure unit test, and any caller that doesn't want the
    extra DB round trip) means "no DB information available" — trust the
    code and let `stage_import_groups`'s own blanket check catch a bad
    one later.

    A `"label"`-kind column looks `raw` (or `IMPORT_NO_VALUE_KEY` for a
    blank cell) up in `value_map`."""
    if kind == IMPORT_COLUMN_KIND_CODE:
        if known_codes is not None and raw not in known_codes:
            return None, f"Unknown account code {raw!r}"
        return raw, None
    code = value_map.get(raw or IMPORT_NO_VALUE_KEY)
    if not code:
        label = raw or "(no value)"
        return None, f"No mapping chosen for {field_label} {label!r}"
    return code, None


def _row_amount(r: dict, amount_style: str, dialect: dict) -> Decimal:
    """The row's own net amount, debit-positive, regardless of whether
    the shape expresses it as one signed `Amount` column or a `Debit`/
    `Credit` pair. Raises `decimal.InvalidOperation` (a non-numeric cell)
    or `ValueError` (a `Debit`/`Credit` pair that isn't exactly one
    positive value — the same "enter exactly one positive Debit or
    Credit" sanity check `parse_csv_import` always enforced, now shared
    by any shape using `amount_style: "debit_credit"`); both are caught
    by `transform_rows`' own per-row error handling."""
    if amount_style == "debit_credit":
        d = parse_amount(r["debit"], dialect) if r["debit"] else Decimal("0")
        c = parse_amount(r["credit"], dialect) if r["credit"] else Decimal("0")
        if d < 0 or c < 0 or (d > 0) == (c > 0):
            raise ValueError("enter exactly one positive Debit or Credit")
        return (d - c).quantize(Decimal("0.01"))
    return parse_amount(r["amount"], dialect).quantize(Decimal("0.01"))


def _amount_error_message(r: dict, amount_style: str) -> str:
    if amount_style == "debit_credit":
        return "Debit/Credit must be numeric"
    return f"Amount {r['amount']!r} isn't numeric"


def transform_rows(rows: list[dict], shape: dict, column_kinds: dict[str, str],
                    value_maps: dict[str, dict[str, str]], flip_sign: bool,
                    dialect: dict = IMPORT_DEFAULT_DIALECT,
                    known_codes: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """(groups, errors) — collapses `transform_mapped_rows`' one-row-per-
    entry logic with a new grouped-rows path, dispatching on `shape[
    "rows_per_entry"]` (IMPORT_WIZARD.md §7 Phase 4 item 3). `errors` is
    always the Phase-3 structured `{row_no, raw, message}` shape — the
    one place the two importers' formerly-different error shapes
    (`parse_csv_import`'s flat strings vs `transform_mapped_rows`'
    structured dicts) get reconciled, onto the richer of the two. Pure —
    no `Connection` (R12); see `known_codes`/`_resolve_leg_account` for
    how a "code"-kind column's existence still gets checked without one.

    **"N legs" means N *rows* sharing one `group_key`, not an N-way split
    expressed by a single row** — the honest scope for Phase 4 item 3's
    own wording. A `"one"` shape entry always has exactly two legs (the
    money account and one "other" account); R9 (a single row expressing
    an arbitrary multi-way split) stays a separate, deferred requirement,
    not attempted here."""
    if shape.get("rows_per_entry") == "grouped":
        return _transform_grouped_rows(rows, shape, column_kinds, value_maps, dialect, known_codes)
    return _transform_one_row_entries(rows, shape, column_kinds, value_maps, flip_sign, dialect, known_codes)


def _transform_one_row_entries(rows: list[dict], shape: dict, column_kinds: dict[str, str],
                                value_maps: dict[str, dict[str, str]], flip_sign: bool,
                                dialect: dict, known_codes: set[str] | None) -> tuple[list[dict], list[dict]]:
    """`rows_per_entry: "one"` — the mapped importer's original logic
    (unchanged 2-leg shape: the money account and one "other" account),
    generalized to resolve each leg via `_resolve_leg_account` (direct
    code or value-map lookup, per `column_kinds`) instead of always
    assuming a label needing `account_map`/`category_map`, and to accept
    either a signed `Amount` or a `Debit`/`Credit` pair via `_row_amount`."""
    account_kind = column_kinds.get("account", IMPORT_DEFAULT_COLUMN_KIND)
    category_kind = column_kinds.get("category", IMPORT_DEFAULT_COLUMN_KIND)
    account_map = value_maps.get("account", {})
    category_map = value_maps.get("category", {})
    amount_style = shape.get("amount_style", "signed")

    groups, errors = [], []
    for r in rows:
        money_code, err = _resolve_leg_account("account", r["account"], account_kind, account_map, known_codes)
        if err:
            errors.append({"row_no": r["row_no"], "raw": r, "message": err})
            continue
        other_code, err = _resolve_leg_account("category", r.get("category", ""), category_kind,
                                                 category_map, known_codes)
        if err:
            errors.append({"row_no": r["row_no"], "raw": r, "message": err})
            continue
        try:
            amount = _row_amount(r, amount_style, dialect)
        except (InvalidOperation, ValueError):
            errors.append({"row_no": r["row_no"], "raw": r, "message": _amount_error_message(r, amount_style)})
            continue
        if flip_sign and amount_style == "signed":
            amount = -amount
        if amount_style == "signed" and amount == 0:
            continue  # nothing to post — same "zero-amount rows are silently skipped" rule as always
        try:
            entry_date = parse_date(r["date"], dialect)
        except ValueError:
            date_label = _DATE_FORMAT_LABELS.get(dialect.get("date_format", "iso"), "YYYY-MM-DD")
            errors.append({"row_no": r["row_no"], "raw": r,
                            "message": f"Invalid Date {r['date']!r} — expected {date_label}"})
            continue
        memo = r.get("memo") or None
        # Standard expense-tracker sign convention (negative = money out):
        # debit whichever side increases, credit whichever side decreases.
        if amount < 0:
            lines = [{"code": other_code, "amount": -amount, "memo": memo},
                     {"code": money_code, "amount": amount, "memo": memo}]
        else:
            lines = [{"code": money_code, "amount": amount, "memo": memo},
                     {"code": other_code, "amount": -amount, "memo": memo}]
        groups.append({
            "entry_date": entry_date.isoformat(),
            "description": r.get("description") or r.get("payee") or r.get("category") or "Imported transaction",
            "reference": None, "payee_name": r.get("payee") or None, "lines": lines,
        })
    return groups, errors


def _transform_grouped_rows(rows: list[dict], shape: dict, column_kinds: dict[str, str],
                             value_maps: dict[str, dict[str, str]], dialect: dict,
                             known_codes: set[str] | None) -> tuple[list[dict], list[dict]]:
    """`rows_per_entry: "grouped"` — `parse_csv_import`'s original
    grouping logic, generalized to resolve each row's own `account` leg
    via `_resolve_leg_account` (a direct code, matching every file this
    shape has ever actually seen, or a value-map lookup — a genuinely new
    capability) instead of always assuming a real code, and to accept
    either a signed `Amount` or a `Debit`/`Credit` pair per row via
    `_row_amount`. Rows are grouped by `group_key` in first-seen order,
    exactly as `parse_csv_import` always grouped by `Entry #`.

    A row with a blank `group_key` gets its own error and joins no group,
    same as a blank `Entry #` always did. A group where any row fails to
    resolve is dropped entirely (no partial-group staging, same as
    always); a group whose legs don't sum to zero is dropped with
    **exactly one** structured error keyed to its first row — not one per
    row in the group, matching `parse_csv_import`'s own per-group (not
    per-row) balance-error granularity."""
    account_kind = column_kinds.get("account", IMPORT_DEFAULT_COLUMN_KIND)
    account_map = value_maps.get("account", {})
    amount_style = shape.get("amount_style", "signed")

    raw_groups: dict[str, list[dict]] = {}
    order: list[str] = []
    errors = []
    for r in rows:
        key = r.get("group_key", "")
        if not key:
            errors.append({"row_no": r["row_no"], "raw": r, "message": "Missing Entry Group value"})
            continue
        if key not in raw_groups:
            raw_groups[key] = []
            order.append(key)
        raw_groups[key].append(r)

    groups = []
    for key in order:
        group_rows = raw_groups[key]
        first = group_rows[0]
        lines, ok = [], True
        for r in group_rows:
            code, err = _resolve_leg_account("account", r.get("account", ""), account_kind, account_map,
                                              known_codes)
            if err:
                errors.append({"row_no": r["row_no"], "raw": r, "message": err})
                ok = False
                continue
            try:
                amount = _row_amount(r, amount_style, dialect)
            except (InvalidOperation, ValueError):
                errors.append({"row_no": r["row_no"], "raw": r,
                                "message": _amount_error_message(r, amount_style)})
                ok = False
                continue
            if amount_style == "signed" and amount == 0:
                continue  # an empty leg — nothing to post for this row
            lines.append({"code": code, "amount": amount, "memo": r.get("memo") or None})
        if not ok or not lines:
            continue
        total = sum(ln["amount"] for ln in lines)
        if total != 0:
            errors.append({"row_no": first["row_no"], "raw": first,
                            "message": f"doesn't balance (off by {total:+.2f})"})
            continue
        try:
            entry_date = parse_date(first["date"], dialect)
        except ValueError:
            date_label = _DATE_FORMAT_LABELS.get(dialect.get("date_format", "iso"), "YYYY-MM-DD")
            errors.append({"row_no": first["row_no"], "raw": first,
                            "message": f"Invalid Date {first['date']!r} — expected {date_label}"})
            continue
        description = first.get("description", "")
        if not description:
            errors.append({"row_no": first["row_no"], "raw": first, "message": "Missing Entry Description"})
            continue
        groups.append({
            "entry_date": entry_date.isoformat(), "description": description,
            "reference": first.get("reference") or None,
            "payee_name": first.get("payee") or None,
            "lines": lines,
        })
    return groups, errors


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
                           flip_sign: bool, dialect: dict = IMPORT_DEFAULT_DIALECT) -> tuple[list[dict], list[dict]]:
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
    it's the only place those three dialect fields matter at all.

    `errors` is a list of `{row_no, raw, message}` dicts, one per failing
    row (IMPORT_WIZARD.md §7 Phase 3 item 1) — not a pre-formatted
    "Row N: ..." string. `raw` is the row's own dict exactly as `parse_
    mapped_file` produced it (its already-mapped Account/Date/.../Amount
    values, still unparsed strings), so a validation-report UI can show
    what was actually in the file next to why it failed, rather than
    only a joined message. Untruncated — `IMPORT_MAX_ERRORS_SHOWN`
    truncation is a display concern now, applied by whatever renders
    this list, not baked into the value a caller gets back."""
    groups, errors = [], []
    for r in rows:
        money_code = account_map.get(r["account"])
        if not money_code:
            errors.append({"row_no": r["row_no"], "raw": r,
                            "message": f"No mapping chosen for account {r['account']!r}"})
            continue
        cat_key = r["category"] or IMPORT_MAPPED_NO_CATEGORY
        other_code = category_map.get(cat_key)
        if not other_code:
            label = r["category"] or "(no category)"
            errors.append({"row_no": r["row_no"], "raw": r,
                            "message": f"No mapping chosen for category {label!r}"})
            continue
        try:
            amount = parse_amount(r["amount"], dialect).quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append({"row_no": r["row_no"], "raw": r,
                            "message": f"Amount {r['amount']!r} isn't numeric"})
            continue
        if flip_sign:
            amount = -amount
        if amount == 0:
            continue
        try:
            entry_date = parse_date(r["date"], dialect)
        except ValueError:
            date_label = _DATE_FORMAT_LABELS.get(dialect.get("date_format", "iso"), "YYYY-MM-DD")
            errors.append({"row_no": r["row_no"], "raw": r,
                            "message": f"Invalid Date {r['date']!r} — expected {date_label}"})
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


def validate_mapped(content: str, column_map: dict[str, str], account_map: dict[str, str],
                     category_map: dict[str, str], flip_sign: bool,
                     dialect: dict = IMPORT_DEFAULT_DIALECT) -> dict:
    """The review step's own pre-commit validation report (IMPORT_WIZARD.md
    §3 step 5, §7 Phase 3) — runs the exact same `parse_mapped_file` +
    `transform_mapped_rows` pipeline `import_mapped` commits with, against
    the same account/category maps, but never touches the database and
    never stages anything. Lets the frontend show every row that would
    fail and why *before* the user decides whether to stage the rest and
    skip them (`import_mapped`'s own `skip_bad_rows`) — R1's "sniff/check
    first, ask second" applied to committing, not just to the earlier
    sniffing steps. Raises `ValueError` on the same structural (pre-row)
    failures `preview_mapped` already raises for — an incomplete or
    wrong `column_map` is caught before any row is even attempted, same
    as it always was; only row-level failures come back as data here."""
    rows, errors = parse_mapped_file(content, column_map, dialect)
    if errors:
        raise ValueError("; ".join(errors))
    groups, row_errors = transform_mapped_rows(rows, account_map, category_map, flip_sign, dialect)
    return {"groups_count": len(groups), "errors": row_errors}


def import_mapped(conn: Connection, *, content: str, filename: str, target_scenario_id: int,
                   column_map: dict[str, str], account_map: dict[str, str], category_map: dict[str, str],
                   flip_sign: bool, dialect: dict = IMPORT_DEFAULT_DIALECT, skip_bad_rows: bool = False,
                   user_id: int | None = None) -> dict:
    """The mapped importer's commit step — ported from `import_mapped_
    commit`'s try block, minus the base64/hidden-form-field round-trip
    (see `router.py`'s own docstring on why the wire shape changed, not
    the behavior). `column_map` is re-applied here rather than trusted
    from the preview step's own response, same "never trust caller-
    supplied structure without re-deriving it" reasoning `stage_import_
    groups`' own account-code re-resolution already documents. `dialect`
    gets the same treatment for the same reason.

    **`skip_bad_rows` makes a partial import an explicit choice, not an
    implicit default** (IMPORT_WIZARD.md §7 Phase 3 item 2). Row errors
    used to mean "stage whatever worked, report the rest" unconditionally
    — now, unless the caller explicitly opts in, any row error blocks the
    whole commit, same as a structural `parse_mapped_file` error already
    did. The intended caller (`ImportMappedPanel.tsx`) always calls
    `validate_mapped` (via `POST /import/mapped/validate`) first and only
    ever sets `skip_bad_rows=True` once a user has actually seen those
    errors and chosen to skip them; a caller that posts straight here
    with row errors present and `skip_bad_rows` left `False` gets exactly
    the same block an API-only consumer should get — no silent partial
    stage."""
    rows, errors = parse_mapped_file(content, column_map, dialect)
    if errors:
        raise ValueError("; ".join(errors))
    groups, row_errors = transform_mapped_rows(rows, account_map, category_map, flip_sign, dialect)
    if row_errors and not skip_bad_rows:
        messages = [e["message"] for e in row_errors[:IMPORT_MAX_ERRORS_SHOWN]]
        raise ValueError("; ".join(messages))
    if not groups:
        raise ValueError("No valid entries produced — check the mapping")
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
