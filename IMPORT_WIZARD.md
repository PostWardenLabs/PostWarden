# The Import Wizard — spec and implementation roadmap

Written in response to a direct request: plan the import wizard properly
before building further, on the stated assumption that **the wizard will
eventually be the only import path in PostWarden**, replacing both of
today's importers, for double-entry and single-entry files alike. Not
everything here gets built now — this is the roadmap, and §7 says what
order to build it in.

**This file is the standing reference for planning any future import
change.** Like `BACKLOG.md` and `UI_CONSISTENCY_AUDIT.md`, it's internal
planning, deliberately not in `mkdocs.yml`'s nav — the published
reference for what the importer *does* stays `README.md` and `SPEC.md`.

---

## 1. Where things actually stand

Two importers, one shared landing point.

| | Plain (`POST /import`) | Mapped (`POST /import/mapped/*`) |
|---|---|---|
| Input | a file that is *already* double entry | a single-entry export (ActualBudget-shaped) |
| Steps | one — upload and go | three — upload → map columns → review |
| Row → entry | several rows grouped by `Entry #` | one row = one entry |
| Amount | separate `Debit`/`Credit` columns | one signed `Amount` column |
| Account | the cell **is** a real account code | the cell is a label, mapped to an account |
| Column names | fixed, required exactly | mapped, any names (as of `v0.31.x`) |
| Produces | `groups` | `groups` |

That last row is the important one. Both funnel through
[`stage_import_groups`](src/postwarden/modules/imports/service.py:176),
which takes a list of `{entry_date, description, reference, payee_name,
lines: [{code, amount, memo}]}` and does everything else. **The wizard's
entire job is to turn a file into that shape.** Merging the two
importers is therefore not a rewrite — it's building one front end that
can emit `groups` from any file, with the differences in the table above
demoted from "which importer did you pick" to "what the wizard sniffed
about your file."

Everything downstream of `groups` — batch rows, payee upsert, deferred
constraint checks, landing in Staging — is already shared and needs no
change for any of this.

### 1.1 The current target-field list is the importer's vocabulary, not the ledger's

[`IMPORT_MAPPED_FIELDS`](src/postwarden/modules/imports/service.py:68)
holds six targets — Money Account, Entry Date, Amount, Payee, Notes,
Category. They aren't "PostWarden's fields" in any general sense: they
are exactly the argument list of
[`transform_mapped_rows`](src/postwarden/modules/imports/service.py:310),
which needs a money account, a date, an amount, a category for the other
leg, a payee for the description and payee record, and notes for the
line memo. It's a leaky abstraction that is currently small enough not
to look like one. It cannot describe an N-leg entry, a Debit/Credit
pair, or a column holding real account codes — i.e. it cannot describe
the plain importer's own files at all.

---

## 2. Decision: the mapping table is oriented file-column → target

Today's mapping step is **target field → file column**: six fixed rows
(one per target), each with a dropdown of the file's columns. It should
be **one row per column found in the file**, each with a dropdown of
PostWarden targets, defaulting to *Ignore*:

| Import file column | Target data field |
|---|---|
| `Account` | Money account |
| `Date` | Entry date |
| `Payee` | Payee |
| `Notes` | Entry description |
| `Category_Group` | _(Ignore)_ |
| `Category` | Category account |
| `Amount` | Amount |
| `Split_Amount` | _(Ignore)_ |
| `Cleared` | _(Ignore)_ |

The current orientation was chosen for three real reasons, all of which
have answers:

- *Required-field validation reads at a glance* — "Amount: — unmapped —"
  is visibly wrong, whereas spotting an **absence** across a 28-row table
  is not. **Answer:** a live "still needed: Amount, Entry date" strip
  above the table, which is more legible than the old version anyway.
- *"Ignore" needs no explicit option* — an unpicked column is ignored.
  **Answer:** that's exactly the problem, see below.
- *The table stays six rows however wide the file is.* **Answer:** true,
  and worth the cost.

The reason to flip anyway: **the file-column orientation forces an
explicit decision about every column in the file.** The current one
silently discards columns the user never sees listed. On a 28-column
bank export the user cannot tell whether the importer understood their
file or ignored two thirds of it. An explicit `_(Ignore)_` is an audit
trail of a decision, not noise. It also reads directly against the
sample-data preview, since both are keyed on the file's own columns.

### 2.1 Sub-decision: Entry description and Line memo are separate targets

The original spec for this table mapped `Notes` → **Entry Description**.
The shipped code maps `payee` → the entry description and `notes` → the
line memo, falling back
`payee or category or "Imported transaction"`. Both are legitimate;
neither should be implicit. The target list gets *Entry description* and
*Line memo* as distinct options, with the fallback chain documented in
the UI ("if nothing is mapped here, the payee is used") rather than
buried in
[`transform_mapped_rows`](src/postwarden/modules/imports/service.py:310).

---

## 3. The step spine

| Step | What it decides | Today |
|---|---|---|
| **0. File** | scenario + upload | ✅ |
| **1. Dialect** | delimiter, quote char, encoding, header row / skip N leading rows, decimal + thousands separator, date format, currency symbols, sign convention | ❌ |
| **2. Shape** | one row per entry vs. rows grouped by a key column; one signed Amount vs. a Debit/Credit pair | ❌ hardcoded, one answer per importer |
| **3. Column mapping** | §2's table; available targets depend on step 2 | ⚠️ wrong orientation, dialect-blind |
| **4. Value mapping** | for each column flagged "needs lookup," every distinct value → a real account (or payee, or tag) | ⚠️ hardcoded to Account + Category |
| **5. Validation report** | every row that couldn't be read, why, and "skip those N, import the other M" | ❌ one flat error banner |
| **6. Confirm** | stage into Staging | ✅ |

Step 2 is the structural key. **"Does one file row equal one entry, or
do several rows combine into one?"** is the single question that
separates the two importers today —
[`parse_csv_import`](src/postwarden/modules/imports/service.py:87)
groups on `Entry #`,
[`parse_mapped_file`](src/postwarden/modules/imports/service.py:253)
doesn't group at all. Make it a wizard setting and the fork disappears.

Step 4's generalization is the other half. Whether a column holds *real
account codes* (plain) or *labels needing a lookup table* (mapped) is a
per-column property, set in step 3, not a property of which importer you
chose. Once step 3 can say "this column contains account codes," the
plain importer is just a wizard configuration.

Both steps must be **sniffable**: a `Debit`+`Credit` header pair, or a
candidate key column with repeated values, are strong signals. See R1.

---

## 4. Requirements

**R1 — Sniff first, ask second.** Every step arrives pre-filled with a
guess and stays editable. A wizard that asks six questions where the old
fixed-column importer asked zero is a regression however capable it is.
Delimiter, decimal separator, date format, header-row presence and
Debit/Credit-pair detection are all inferable from a handful of rows
with high confidence.

**R2 — The preview is always the file's real data, at every step.** Step
1 shows parsed cells, step 3 shows mapped columns, step 5 shows the
resulting **journal entries** with their legs and balance. Never an
abstract summary. This is why
[`sniff_mapped_columns`](src/postwarden/modules/imports/service.py:232)
already returns real sample rows and not just header names.

**R3 — Per-row error reporting.** Today a bad file is one red banner of
up to `IMPORT_MAX_ERRORS_SHOWN` joined messages. It should be a table —
row number, the raw row, what failed — with a "skip these N rows and
import the other M" action. (This is `BACKLOG.md`'s own "Ensure that the
import functionality currently flags entries it can't handle" item.)

**R4 — Duplicate protection.** Once this is the only import path,
re-importing an overlapping statement stops being an edge case. At
preview time: "12 of these 90 rows match entries already in your
ledger." A per-entry hash of the source row makes this exact rather than
heuristic, and feeds both existing duplicate items (the shipped
`/staging/duplicates` page, and the "Automatically flag possible
duplicates" backlog item).

**R5 — Saved import profiles.** This is a deliberate reversal of
`SPEC.md` decision 23's "no saved, named, reusable ruleset — literally
no new table." That was right for a one-off tool and is wrong for the
only import path: nobody should redo steps 1–4 every month for the same
bank. Steps 1–4 save as a named profile, auto-matched on upload by
column-name fingerprint. Value maps should be sticky too — if
`SAFEWAY #1234` was Groceries last month, propose it this month.

**R6 — Row-level conditional rules.** The known v1 limitation already
written up in `BACKLOG.md`'s Done section: every blank-Category row
lands on whichever single account was chosen for `(no category)`, so an
income row and a cash withdrawal sharing a blank Category cannot both be
right. The fix is a small ordered rule list evaluated per row —
`IF <column> <contains | equals | starts with | matches> <value> THEN
<leg> = <account>` — first match wins, falling back to the step-4 value
map. This is what makes the wizard genuinely replace hand-fixing in
Staging afterwards.

**R7 — Formats beyond comma-separated CSV.** XLSX is already a backlog
item; semicolon/tab-delimited files are the same problem; OFX/QFX/CAMT
are what banks actually emit. **Requirement:** step 1 abstracts "file →
table of strings," and nothing format-specific leaks past it. Every
function from step 2 onward keeps taking parsed rows, never raw bytes.

**R8 — Stop base64-ing the whole file through every step, above some
size.** The stateless round-trip
([`encode_for_roundtrip`](src/postwarden/modules/imports/service.py:399))
is genuinely right at 200 rows and genuinely wrong for a five-year 20 MB
XLSX. Above a threshold, park the upload server-side with a TTL and pass
an id through the wizard instead.

**R9 — Splits.** A single file row representing a multi-leg transaction
(the `Split_Amount` column in §2's table). Either it's covered by step
2's row grouping, or it is explicitly out of scope — but it should be a
decision, not an omission.

**R10 — Decide now whether the wizard's *target* is pluggable.**
`BACKLOG.md` already has "Export/import metadata (Chart of Accounts,
scenarios, payees, tags) from csv files." Steps 1–3 are identical for
that; steps 4–6 are not. Build 1–3 target-agnostic even while shipping
journal entries only — retrofitting it later means rewriting the mapping
step.

**R11 — `stage_import_groups` stays the single funnel.** The wizard
never grows its own staging path, and the old importers are retired only
once the wizard is a strict superset of both.

**R12 — Every step stays a pure function on parsed rows.** The existing
parse/sniff/transform functions take no `Connection` and that is why
`apitests/modules/imports/test_service.py` can cover them exhaustively
with no fixtures. The value of that grows with each step added; it is
not a convention to relax under complexity.

---

## 5. Schema impact

`BACKLOG.md`'s standing question is which features force a wipe and
rebuild. For this one: **none of it does.**

| Requirement | Schema change | Kind |
|---|---|---|
| Steps 0–3, 5, 6; §2's re-orientation | none | pure parse/transform |
| Step 4 generalization | none | still caller-supplied maps |
| R6 conditional rules | none, if rules stay per-import | pure transform |
| R5 saved profiles | new table `import_profiles` (+ value-map rows) | additive |
| R4 duplicate detection | one nullable column on `journal_entries` | additive |
| R8 large-file staging | new table, purgeable, TTL | additive |

All three are ordinary additive Alembic migrations against the baseline
that landed with `v0.31.0`. Nothing is destructive; nothing touches
`journal_lines`, the immutability triggers, or the balance constraint.

---

## 6. What this does to `SPEC.md`

Two decisions will need revising *when the corresponding step ships*,
not before — per the standing documentation rule, in the same piece of
work:

- **Decision 23** ("A rule is three mapping tables scoped to one file,
  not a saved, named, reusable ruleset") is directly reversed by R5.
  When profiles ship, decision 23 gets an addendum explaining that the
  original reasoning held while this was a second, optional importer and
  stopped holding once it became the only one.
- A **new decision** is warranted for the step-2 shape concept — "one
  row per entry vs. grouped by a key column" is the design idea that
  lets one wizard subsume both importers, and it's exactly the kind of
  *why* that `SPEC.md` exists to record.

---

## 7. Implementation steps

Ordered by (value ÷ cost), and so that each phase is independently
shippable and independently revertable — one commit per phase minimum,
more where a phase splits cleanly into backend and frontend the way the
column-mapping step already did.

### Phase 1 — Re-orient the mapping table (small) — ✅ shipped

The §2 decision, plus §2.1. No new capability, but it fixes a real blind
spot in what shipped.

The duplicate-target check (step 2 below) ended up client-side, not in
`service.py` — the wire's `column_map` is single-valued per target by
construction (a dict key holds one value), so by the time a second claim
on one target would reach the backend, the information about the first
claim it silently overwrote is already gone. `ImportMappedPanel.tsx`'s
own per-column state is the only place both claims are still visible at
once. `SPEC.md` decision 23's own account of the re-orientation has the
fuller version.

1. `service.py`: keep `IMPORT_MAPPED_FIELDS` as the canonical target
   list; add `description` and `memo` as distinct targets, and make the
   payee → description fallback explicit rather than implicit in
   `transform_mapped_rows`.
2. `service.py`: `parse_mapped_file`'s `column_map` stays
   target-key → column internally (it's the right shape for the parser);
   the **inversion happens in the frontend**, so the wire format doesn't
   churn. Add a validation error for two columns claiming one
   single-valued target.
3. `ImportMappedPanel.tsx`: the mapping step renders one row per entry
   in `columns.columns`, each with a `Combobox` of targets defaulting to
   *Ignore*; derive the outgoing `column_map` by inverting on submit.
4. Add the "still needed: …" strip, driven by the same
   `required` flags already on `IMPORT_MAPPED_FIELDS`.
5. Tests: `test_service.py` for the new targets and the duplicate-target
   error; browser-verify the table against a wide file (many ignored
   columns), which is the case the current UI cannot express at all.
6. Docs: `SPEC.md` decision 23's column-mapping paragraph, `README.md`
   if the user-visible description changes.

### Phase 2 — Step 1, the dialect controls (medium)

The single thing standing between "ActualBudget-shaped CSVs" and "any
bank's CSV." A European export using `;` and `1.234,56` currently just
fails, with no control anywhere to fix it.

1. New pure `service.sniff_dialect(raw) -> dict` — delimiter, quote
   char, encoding, header row index, decimal/thousands separator, date
   format, each with the guess *and* enough sample evidence for the UI
   to show why.
2. New `parse_rows(raw, dialect) -> list[dict]` as the one entry point
   everything downstream uses; `parse_mapped_file`/`parse_csv_import`
   both refactored to consume its output rather than call
   `csv.DictReader` themselves. This is R7's abstraction boundary, built
   before there's a second format to justify it — cheap now, expensive
   later.
3. Amount parsing moves out of `transform_mapped_rows`' inline
   `Decimal(r["amount"].replace(",", ""))` into a dialect-aware helper.
   Same for the ISO-only `date.fromisoformat` calls.
4. New route `POST /import/mapped/dialect`, or fold it into
   `/mapped/columns`' response as `dialect` + let `/mapped/preview`
   accept an overridden one. Prefer the latter — one fewer round trip,
   and the wizard step is a client-side edit of a server-supplied guess.
5. Frontend: a compact dialect panel above the sample-rows preview,
   re-parsing live as the user changes a setting (R2).
6. Tests: a semicolon/comma-decimal file, a `DD/MM/YYYY` file, a
   BOM'd Excel export, a file with two junk rows above the header.

### Phase 3 — Step 5, the per-row validation report (small–medium)

1. Every parse/transform function already returns `(rows, errors)` —
   change `errors` from `list[str]` to a structured
   `list[{row_no, raw, message}]`, and stop truncating at
   `IMPORT_MAX_ERRORS_SHOWN` on the wire (truncate in the UI instead).
2. `import_mapped` gains a `skip_bad_rows: bool`, so a partial import is
   an explicit choice rather than the current implicit "stage what
   worked, report the rest."
3. Frontend: a real errors table between review and commit, with the
   skip/go-back actions.

### Phase 4 — Steps 2 + 4, and retiring the plain importer (large)

The actual merge. Materially easier once phases 1–3 exist.

1. `service.py`: a `shape` concept — `{rows_per_entry: "one" | "grouped",
   group_key_column, amount_style: "signed" | "debit_credit"}` — plus
   sniffing for it.
2. Step 3's per-column property: *contains account codes* vs. *contains
   labels to map*. This is the change that lets step 4 generalize from
   two hardcoded maps (`account_map`, `category_map`) to one map per
   lookup column.
3. `parse_csv_import` and `parse_mapped_file` collapse into one
   `parse_file(rows, shape, column_map)`; `transform_mapped_rows`
   generalizes to N legs.
4. `POST /import` (plain) becomes a thin compatibility shim over the
   wizard pipeline, then is removed once nothing calls it.
5. Frontend: `ImportPlainPanel.tsx` is deleted; `ImportPage.tsx` loses
   its tabs and becomes the wizard.
6. Docs: the new `SPEC.md` decision from §6, `docs/ARCHITECTURE.md` for
   the frontend change, `README.md`'s "What you get."

### Phase 5 and beyond — in whatever order pain dictates

- **R5 profiles** — first schema change; biggest quality-of-life win for
  a real recurring workflow.
- **R6 conditional rules** — closes the documented v1 limitation.
- **R7 XLSX** — cheap *if* phase 2's boundary held.
- **R4 duplicate detection** — most valuable once imports are frequent
  enough to overlap, which is a consequence of R5 existing.
- **R8 large-file handling** — driven by real file sizes, not
  speculatively.
- **R9 splits**, **R10 metadata import** — decide, then schedule.
