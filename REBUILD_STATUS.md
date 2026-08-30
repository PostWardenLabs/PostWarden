# Rebuild status — where we are, what's next

This is the companion tracker to [`REBUILD.md`](REBUILD.md). Keep the two
separate on purpose: **`REBUILD.md` is the *why*** — context, numbered
decisions, rejected alternatives, the stop conditions. **This file is the
*where are we right now*** — a concrete, checkable step sequence, updated
as work actually happens. Like `REBUILD.md`, `BACKLOG.md`, and
`UI_CONSISTENCY_AUDIT.md`, it is internal planning and deliberately not in
`mkdocs.yml`'s nav.

**The sequence below is a plan, not a contract.** We re-evaluate what's
next continuously. When the order changes for a reason worth remembering,
that's a `REBUILD.md` §5-style decision (rejected alternative and all) —
this file just gets re-checked off against whatever the current plan is.
Small reorderings that aren't really "decisions" (moved a CRUD screen
earlier because it was blocking something) just get reflected here with a
note in the log.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done

---

## Current status

**Phase 0 done.** `backend/` exists as a `src`-layout package with the full
tree, dependencies pinned, a smoke test proving the pipeline (install →
import → `TestClient` → assert) works, an Alembic baseline that reproduces
`db/schema.sql` exactly, CI (`.github/workflows/backend-ci.yml`)
exercising both against a real Postgres service container, and its own
`docker-compose.yml` for local dev — confirmed clean from a fresh
`up -d --build`, serving `/healthz`, correctly stamped to the baseline,
`seed_demo.sql`'s entries loaded. No `frontend/` yet. `master` is
untouched and still what's deployed.

**Phase 1.1 done.** `domain/money.py`, `periods.py`, `accounts.py`,
`entry.py` — pure logic ported from `app/main.py`'s module-level
helpers, zero framework/IO imports, 48 new unit tests, all green.

**Phase 1.2 done.** `config.py` — a `pydantic-settings` `Settings` class
centralizing the six env vars the legacy app read ad hoc across
`app/db.py`/`app/auth.py`/`app/main.py`. `db.py` — a lazily-built,
cached SQLAlchemy Core `Engine` plus a `get_connection()` FastAPI
dependency (one connection, one transaction per request, mirroring
legacy `app/db.py`'s `tx()`). 7 new unit tests, all green, plus a
one-off manual smoke test against a real `docker compose up -d db` to
confirm the engine actually connects (not just that it constructs).

**Phase 1.3 done.** `json.py` — closes the "documented gap" REBUILD.md §6
flags: a route's `Decimal`/`date` values need fixing in two genuinely
different response paths, both covered now instead of per-route.
`configure_decimal_encoding()` fixes FastAPI's own `jsonable_encoder`
(used on an implicit `return {...}`), which otherwise silently downgrades
`Decimal` to lossy `float`; `date`/`datetime` needed no fix there,
verified rather than assumed. `JSONResponse` (same name/constructor as
`fastapi.responses.JSONResponse`) fixes the explicit
`JSONResponse({"ok": ...})` idiom legacy uses throughout, which Starlette
renders via plain `json.dumps` and which raises outright on a bare
`Decimal` *or* `date`/`datetime` with no fallback. 9 new unit tests
(direct + end-to-end `TestClient` for both paths), all green. Wired into
`main.py`'s app factory: `configure_decimal_encoding()` called at import
time, `app`'s `default_response_class` set to the new `JSONResponse`.
Verified with a real `docker compose up -d --build`: clean startup log,
`/healthz` still 200.

**Phase 1.4 done.** `modules/reports/` — `repository.py` (raw SQL/SRF
access), `service.py` (report assembly, including the ~450 "genuinely
hard" lines: `income_statement_matrix`/`scale_income_statement_result`,
`cash_flow_rows`/`cash_flow_tie_out`, `compute_variance`'s dual native-
depth/rolled-up path, plus the "mechanical" wrapper functions those and
the routes need — `trial_balance`, `balance_sheet`,
`income_statement_rows`/`income_statement_balances`), and `router.py`
(five GET endpoints, one per report). `income_statement_groups` — pure,
no DB — joined `domain/accounts.py` instead of `service.py`, alongside
`build_account_tree`/`flatten_tree` from Phase 1.1. Reports still call
`fn_trial_balance`/`fn_account_balances`/`fn_cash_flow_lines`/
`fn_rollup_balance` directly through raw SQL, not modeled through
SQLAlchemy Core, per REBUILD.md §6. Router built but not yet mounted
into `app` — real mounting is Phase 1.14, once every module has one. 28
new tests (5 pure `domain/accounts.py` tests, no DB; 23 DB-backed
`modules/reports/` tests against a real Postgres scratch database this
phase's own `backend/tests/conftest.py` now creates from `db/schema.sql`
alone), all green — 93 passed total. Verified with a real `docker
compose up -d --build`: clean startup log, `/healthz` still 200; also
verified the exact CI shape by hand (a bare `postgres:16` container,
`alembic upgrade head`, `pytest`) since this phase's tests are the first
in `backend/` to actually touch a database.

**Phase 1.5 done.** `modules/entries/` — the Journal backend:
`schemas.py` (the one module so far that needs Pydantic request bodies —
every route here is a POST, unlike reports' all-GET shape),
`repository.py`, `service.py`, `router.py` (six routes: list/filter/
paginate, create, single reverse, bulk reverse, bulk tag edit, edit
description, edit line memo — eight, counting both edit routes
separately). Two things surfaced here that reports' read-only shape
never exercised, both worth carrying forward to every future write
module:

1. **`errors.py`, new** — `pg_message()`, ported from legacy `_pg_msg`,
   unwrapping `sqlalchemy.exc.DBAPIError.orig` before extracting a
   trigger's own `RAISE EXCEPTION` text. Not entries-specific: every
   future write module (`staging`, `budget`, `imports`, `reference`,
   `scheduling`) needs the identical unwrap, so it's centralized now
   rather than copy-pasted later, same "documented gap, not theoretical"
   reasoning `json.py` (Phase 1.3) applied to Decimal/date encoding.
2. **`repository.check_deferred_constraints()` — a real interaction with
   `db.get_connection()`'s design (Phase 1.2), not a hypothetical one.**
   The balance/has-lines invariants are `DEFERRABLE INITIALLY DEFERRED`
   — they fire at COMMIT. Legacy's `tx()` commits at the end of each
   route's own block, so a violation always lands in that same route's
   `except`. `get_connection()` instead commits once, when its own
   generator resumes *after* the route returns — so left alone, an
   unbalanced entry would still be rejected, just as an unhandled
   exception raised after `create_entry` already returned 201, surfacing
   as a bare 500 instead of a 400 with `pg_message`'s extracted text.
   Fixed with `SET CONSTRAINTS ALL IMMEDIATE`, called right after a
   function's last line insert, forcing the deferred triggers to run at
   a point the caller's own `try/except` still covers.

   **This needed a second fix once actually run against Postgres, not
   just reasoned about.** `SET CONSTRAINTS ALL IMMEDIATE` is a standing
   mode change for the rest of the transaction, not a one-shot check —
   caught by `test_reverse_entries_bulk_a_duplicate_id_reverses_once_
   and_reports_the_second` and two others failing with "entry ... has no
   lines" on the *header insert itself* of a *second* entry-creating
   call in the same test, before its lines had a chance to be copied in.
   `create_entry`'s own `check_deferred_constraints` call had left the
   connection in `IMMEDIATE` mode for the rest of that test's shared
   transaction, so `reverse_entry`'s later header-then-lines sequence no
   longer got the deferred window it needs. Fixed by having
   `check_deferred_constraints` set the mode back to `DEFERRED`
   immediately after a passing `IMMEDIATE` check (only the passing path
   needs this — a raised violation means the caller's own `begin_
   nested()` savepoint or the request's own rollback undoes the mode
   change along with everything else, per Postgres's own semantics for
   `SET CONSTRAINTS` across `ROLLBACK TO SAVEPOINT`). Left as a one-line
   fix easy to get wrong quietly: without a test that does two
   entry-creating operations in the same transaction, this would have
   shipped working in every one-off case and broken exactly the bulk-
   reversal path that most needs the deferred window.
3. **`reverse_entries_bulk` uses `Connection.begin_nested()` (a
   SAVEPOINT) per entry, not a bare loop.** Legacy's version calls
   `_reverse_one_entry` in a loop where each call opens and commits its
   own `tx()`, so one bad entry in the batch is independent of every
   other. `get_connection()` gives the whole request one transaction, so
   a bare loop would behave *worse* than legacy: Postgres aborts an
   entire transaction on its first error, so entry #2 failing would
   silently take #3 onward down with it too. A `SAVEPOINT` per entry
   restores legacy's true per-entry independence inside the one shared
   transaction. `test_reverse_entries_bulk_one_bad_id_does_not_stop_the_
   rest` deliberately puts the bad id *first* in the batch to prove a
   later success isn't collateral damage.

Other decisions, smaller:

- **Entry list responses nest `lines`/`tags` directly under each entry**
  (`{"entries": [{..., "lines": [...], "tags": [...]}]}`), not legacy's
  three parallel dicts (`entries`/`lines_by_entry`/`tags_by_entry`) a
  Jinja template re-joined by id at render time. A JSON API consumer has
  no reason to redo grouping the backend already did.
- **No `created_by_user_id`/reversed-by attribution, no CSRF check.**
  Both are `modules/auth/` (Phase 1.11) concerns; every write posts with
  `created_by_user_id = NULL` for now (the column is nullable for
  exactly this reason — `db/schema.sql`'s own comment). Same "don't
  reach into a module that doesn't exist yet" reasoning Phase 1.4 #4
  applied to `modules/reference/`.
- **No CSV/XLSX export routes.** Those belong to the shared `export/`
  module (Phase 1.12); `service.list_entries`/`repository.build_filter`
  are already shaped so 1.12 can reuse them unchanged — same filters,
  same WHERE clause, the way legacy's own `_entries_filter` was shared
  three ways.
- **The entries/staging shared filter builder (legacy's `_shared_
  journal_filters`) stays in `modules/entries/repository.py`, not a
  common location** — only entries needs it in this phase; Phase 1.6
  (`modules/staging/`) decides then whether to import `build_filter`
  from here or fork its own copy.
- **`schemas.EntryLineIn` keeps `debit`/`credit` as plain strings**, not
  Pydantic `Decimal` fields — `domain.entry.parse_lines` already does
  the string -> `Decimal` parsing (and its own tested validation
  messages) against parallel string lists; a separate Pydantic numeric
  field would mean the same question answered twice, possibly
  disagreeing. The router unzips `list[EntryLineIn]` back into parallel
  lists immediately before calling `parse_lines`.

46 new tests (15 `repository.py`, 16 `service.py`, 11 `router.py`; `test_
errors.py`'s 4 are top-level, not entries-specific) — 139 passed total.
Verified for real, twice over: a full `docker compose up -d --build`
(clean log, `/healthz` 200), and separately, the exact CI shape by hand
(a bare `postgres:16` container, `alembic upgrade head`, `pytest`) —
which is what actually caught the `SET CONSTRAINTS` bug above, since
`pytest -q`'s full-suite run (not a single test in isolation) is what
put `create_entry` and `reverse_entry` in the same shared transaction
the bug depended on.

**Phase 1.6 done.** `modules/staging/` — the layover a scheduled entry's
occurrence or a CSV import row sits in until a human approves it:
`schemas.py`, `repository.py`, `service.py`, `router.py` (eight routes:
list/filter pending entries, bulk approve, get/save the inline edit
panel's data, single reject, bulk reject, find duplicates, merge
duplicates). Two decisions worth recording:

1. **Forked `modules/entries/`'s shared filter-fragment builder and a
   handful of small helpers (`account_ids_by_code`, `insert_entry`/
   `insert_line`-equivalents, `sync_entry_tags`, tag/line lookups)
   rather than importing them**, closing the question Phase 1.5's own
   `repository.py` docstring left open. REBUILD.md decision 3's test —
   "a module should be deletable on its own" — settles it: importing
   `build_filter` from `modules/entries/` would mean deleting that
   module breaks this one, even though nothing about approving a staged
   entry depends on the Journal. The shared fragments (date range,
   free-text search, tags, account, payee, amount operator — legacy's
   own `_shared_journal_filters`) are ~25 lines; paying that duplication
   once here is cheaper than the coupling compounding across every
   future module that also needs entry filtering (`budget`, `imports`).
2. **One real consolidation, not just a fork.** Legacy has two near-
   duplicate versions of "resolve this staged entry's target scenario,
   default to ACTUAL, validate it's still pending" — the inline block in
   `approve_staging_entries` (error text "no target scenario to approve
   into") and the shared `_pending_staging_entry` every other caller
   (edit/reject/merge) uses (error text "no target scenario"). Both
   collapse into one function, `service._validate_pending`, called by
   every write path in this module — one message, not two slightly
   different ones for the same condition.

Other decisions, smaller:

- **`staged_entry`'s response has no `target_scenario`/`accounts`
  picker payload**, unlike legacy's `staging_edit_data` (which embedded
  the full scenario row and that scenario's postable-accounts list).
  Same "don't reach into a module that doesn't exist yet" reasoning
  Phase 1.4 and 1.5 both already applied to `modules/reference/` (Phase
  1.9) — `target_scenario_id` (a fact about *this* staged entry) stays,
  the reference-data lookups don't.
- **`repository.all_pending_entries_basic` (backing `find_duplicate_
  groups`) does not filter on `promoted_entry_id IS NULL`, matching
  legacy's `_find_staging_duplicate_groups` exactly** — an already-
  approved staging-origin entry (its `promoted_entry_id` set, but the
  row itself never moved or got deleted) stays a duplicate-matching
  candidate. Ported as-is rather than fixed: REBUILD.md decision 4 is
  explicit that this rebuild ports behavior, not silently corrects it
  outside the golden-master question, and `staging/duplicates` is one of
  REBUILD.md §4's own named blind spots (zero test coverage in the
  current app) — there's no way to tell from here whether this is a bug
  or deliberate. Documented prominently in `repository.py`'s own
  docstring and exercised directly by its own test
  (`test_all_pending_entries_basic_includes_already_promoted_entries`)
  so a future session doesn't mistake it for an oversight in the port.
- **`backend/tests/conftest.py`'s `mk_entry` gained four new optional
  keyword-only params** (`reference`, `payee_id`, `scheduled_entry_id`,
  `import_batch_id`, `promoted_entry_id`) — needed because `fn_staging_
  manual_entry_guard` (`db/schema.sql`) rejects a staging-scenario
  insert with neither `scheduled_entry_id` nor `import_batch_id` set, so
  this module's own tests need a way to build a legitimately-staged
  fixture row. Backward compatible: every existing four-positional-arg
  call site (`modules/entries/`, `modules/reports/`) is unchanged.
- **`MergeDuplicatesRequest.line_memos` is a `{line_id: memo}` JSON
  object**, not legacy's parallel `memo_<line_id>` form fields — same
  "ignore whatever key doesn't belong to a line the survivor actually
  has" behavior as legacy's own `form.get(f"memo_{row['id']}")` lookup,
  just JSON-shaped instead of form-field-name-shaped.

52 new tests (16 `repository.py`, 23 `service.py`, 13 `router.py`) — 191
passed total. Verified for real, the same three ways as every phase
since 1.4: a full `docker compose up -d --build` (clean log, `/healthz`
200), a local `docker compose up -d db` + `pytest` run, and separately
the exact CI shape by hand (a bare `postgres:16` container, `alembic
upgrade head`, `pytest`).

**Phase 1.7 done.** `modules/budget/` — the ActualBudget-style grid for an
income-statement-only scenario: `repository.py`, `service.py`,
`schemas.py`, `router.py` (two routes: `GET /budget` the grid,
`POST /budget/cell` the single-cell upsert). Smaller in scope than 1.4-1.6
— one report-shaped read plus one write, no bulk/filter machinery — and
notably simpler than `modules/entries/`'s own write path for a real
structural reason, not an oversight:

1. **`fn_budget_line_guard` fires immediately, not deferred.** Unlike
   `journal_entries`' balance/has-lines triggers (`DEFERRABLE INITIALLY
   DEFERRED`, SPEC.md decision 2 — the reason `modules/entries/
   repository.py`'s `check_deferred_constraints`/`SET CONSTRAINTS ALL
   IMMEDIATE` exist at all), `trg_budget_line_guard` is a plain `BEFORE
   INSERT OR UPDATE` trigger. A bad scenario/account raises right at the
   `INSERT`, inside whatever `try/except` is already there — no COMMIT-
   timing gap for `db.get_connection()`'s one-transaction-per-request
   design to open up, so `repository.upsert_budget_cell` needed none of
   that machinery.
2. **`dim_accounts`, `account_balances`, and the scenario-by-code lookup
   fork the equivalent queries in `modules/reports/repository.py`**
   rather than importing them — the same "a module should be deletable on
   its own" test (`REBUILD.md` decision 3) `modules/staging/repository.py`
   already applied when it forked `modules/entries/`'s filter builder,
   applied here for the first time against `reports` instead of a sibling
   write module.
3. **One real consolidation, found while porting rather than assumed
   going in.** Legacy's `_budget_rows` carries its own local `flatten()`
   helper — walks the merged tree with no zero-filtering, since a budget
   grid has to show every account whether or not it's been budgeted, so
   you have somewhere to type a number. That turns out to be exactly what
   `domain.accounts.flatten_tree(nodes, zeros=True)` (Phase 1.1) already
   does — `zeros=True` already means "never drop a zero-subtotal branch,"
   and it produces the identical `has_children` for the identical reason.
   `service.budget_grid` calls the existing domain function instead of
   carrying a second, near-duplicate flatten — the same "legacy duplicated
   this exact logic with no shared helper" pattern Phase 1.4 already found
   once (`income_statement_groups`'s own `signed()`, later traced to
   `domain.money.normalize_zero`), which this module's own `merge()`
   closure also reuses for its sign-flip zero guard rather than
   reimplementing it a third time.
4. **`save_budget_cell` parses straight to `Decimal`, not legacy's
   `round(float(amount_raw), 2)`** — the same fix `domain.entry.
   parse_lines` (Phase 1.1) already applied to debit/credit input, for the
   identical reason: every `budget_lines.amount` column is `NUMERIC(18,2)`
   end to end, and `float` was only ever a latent-imprecision risk with no
   upside.
5. **`GET /budget` never picks a *default* scenario when `scenario` is
   omitted**, unlike legacy's `budget_page` (`scens[0]["code"]` — the
   first income-statement-only scenario it finds). Doing that needs the
   full scenario list, which is `modules/reference/` (Phase 1.9) — same
   "don't reach into a module that doesn't exist yet" reasoning every
   report/entries/staging route already applies. An empty, unknown, or
   non-income-statement-only `scenario` all fall through to `service.
   budget_grid`'s zero-figure stub uniformly; the frontend resolves a real
   default from `modules/reference/`'s own scenario list once that exists.
6. **`domain.periods.shift_month`/`month_options` needed no changes at
   all** — both were already ported in Phase 1.1 (`_shift_month`/`_month_
   options` were module-level in `app/main.py`, right next to `_budget_
   rows`, but pure — no framework/IO — so Phase 1.1 moved them to
   `domain/` on sight, ahead of any module actually needing them yet).
   This module is the first to actually call them; `router._resolve_month`
   otherwise ports `budget_page`'s own month-normalization block
   (`YYYY-MM` -> `YYYY-MM-01`, a stale/hand-typed month falling back to
   today rather than a 500 — BACKLOG.md's own note on why the grid's
   month field is a real picker, not a raw date input) verbatim.

26 new tests (8 `repository.py`, 11 `service.py`, 7 `router.py`) — 217
passed total. `backend/tests/conftest.py` gained one new helper,
`mk_budget_line` (mirroring the root `tests/conftest.py`'s own version),
needed because this is the first `backend/` module to test against
`budget_lines` directly. Verified for real, the same three ways as every
phase since 1.4: a full `docker compose up -d --build` (clean log,
`/healthz` 200), a local `docker compose up -d db` + `pytest` run, and
separately the exact CI shape by hand (a bare `postgres:16` container,
`alembic upgrade head`, `pytest`).

**Phase 1.8 done.** `modules/imports/` — both importers (plain CSV,
mapped/rules): `repository.py`, `service.py`, `schemas.py`, `router.py`
(four routes: `GET /import` recent-batches list, `POST /import` the plain
CSV importer, `POST /import/mapped/preview` + `POST /import/mapped` the
mapped importer's two-step flow). The one module so far to need a real
file upload, which surfaced its own small set of decisions:

1. **Forks `modules/entries/repository.py`'s `account_ids_by_code`/
   `check_deferred_constraints` and the "look up the one Staging
   scenario" query rather than importing them** — the same test every
   prior write module's own docstring already applies (REBUILD.md
   decision 3): deleting `modules/entries/` or `modules/staging/` should
   never break `modules/imports/`, even though staging a CSV row doesn't
   depend on either.
2. **One real behavior improvement over a verbatim port, found while
   porting rather than assumed going in.** Legacy's own `_stage_import_
   groups` resolves each line's `account_id` via an inline `(SELECT id
   FROM accounts WHERE code = %s)` subquery — harmless for the plain CSV
   importer (`_parse_csv_import` already validates every code before a
   group is ever returned) but a real gap for the mapped importer, whose
   `account_map`/`category_map` values are caller-supplied and never
   checked against real accounts: an unmapped-to-nothing code would
   silently resolve to `NULL` and only fail later on `journal_lines.
   account_id`'s own `NOT NULL` constraint — a working but unhelpfully
   generic error. `service.stage_import_groups` resolves every code
   across every group up front instead, the same explicit "unknown
   account code" check `modules.entries.service.create_entry` and
   `modules.staging.service.save_edit` already both do, so a bad mapping
   value now fails with a clear message before any row is written.
3. **A second real fix, this one caught only by a test, not by reading
   the code first.** `repository.recent_batches`'s `ORDER BY ib.
   created_at DESC` (legacy's own, verbatim) ties whenever two batches
   land in the same transaction — `now()` returns the *transaction*
   start time in Postgres, identical for every row one transaction
   inserts, a real possibility here since `db.get_connection()` gives one
   request one transaction where legacy's own per-route `tx()` never
   would have. `test_recent_batches_orders_newest_first_and_respects_
   limit` (three batches inserted back to back in one test transaction)
   failed on exactly this before `ib.id DESC` was added as a tiebreaker —
   the fix is one clause, but nothing short of actually running a test
   that inserts more than one batch per transaction would have surfaced
   it, same "this needed a second fix once actually run against
   Postgres, not just reasoned about" pattern Phase 1.5's `SET
   CONSTRAINTS` bug already taught.
4. **Amounts are `Decimal` throughout `parse_csv_import`/`transform_
   mapped_rows`, not legacy's `float(d)`/`round(..., 2)`.** Same fix
   `domain.entry.parse_lines` (Phase 1.1) and `modules.budget.service.
   save_budget_cell` (Phase 1.7) already applied to user-typed money, for
   the identical reason: every amount lands in a `NUMERIC(18,2)` column.
5. **The mapped importer's preview/commit round-trip is JSON-shaped, not
   legacy's hidden-form-fields-plus-base64 shape.** `POST /import/mapped/
   preview` returns the parsed picker lists *plus* the uploaded file's own
   content, base64-encoded; the frontend holds that and sends it back
   verbatim as `schemas.MappedImportCommitRequest.file_content_b64` when
   the mapping is confirmed — the same round-trip legacy's hidden
   `file_b64`/`account_map__<key>`/`category_map__<key>` form fields
   performed, just JSON-shaped instead of form-field-name-shaped, the
   identical adaptation `modules.staging.schemas.MergeDuplicatesRequest.
   line_memos` already made for its own prefixed-form-field precursor.
   Nothing is persisted server-side between the two steps either way,
   matching legacy's own comment that there's "nothing to save, expire,
   or clean up."
6. **No `GET /import/mapped` route at all**, unlike every other GET this
   module or any prior one built. Legacy's own route renders nothing this
   module owns — an empty page whose only real content is the target-
   scenario picker, a `modules/reference/` concern (Phase 1.9) the
   frontend will fetch separately, same "don't reach into a module that
   doesn't exist yet" reasoning every prior module already applies. `GET
   /import`'s own recent-batches listing survives, since that data *is*
   this module's own.

Other decisions, smaller:

- **No CSRF check, no real `imported_by_user_id` attribution** — both
  `modules/auth/` (Phase 1.11) concerns, same two documented gaps every
  prior write module carries; every import runs with `user_id=None`.
- **`insert_staged_entry` sets no `created_by_user_id`**, matching
  legacy's own insert exactly — an entry sitting in Staging isn't yet
  anyone's manual posting; that only gets set on the *approved* copy
  `modules.staging.service.approve_entry` creates.

38 new tests (7 `repository.py`, 24 `service.py`, 7 `router.py`) — 255
passed total. `backend/tests/modules/imports/conftest.py`'s own `book`
fixture is the first to need a *third* postable account (`5100 Rent`,
expense) alongside the usual Checking/Salary pair, since the mapped
importer needs a real Category-side account distinct from the
Account-side (money) one. Verified for real, the same three ways as
every phase since 1.4: a full `docker compose up -d --build` (clean log,
`/healthz` 200), a local `docker compose up -d db` + `pytest` run, and
separately the exact CI shape by hand (a bare `postgres:16` container,
`alembic upgrade head`, `pytest`).

**Phase 1.9 done.** `modules/reference/` — Accounts, Account levels,
Scenarios, Payees, Tags: `repository.py`, `service.py`, `schemas.py`,
`router.py` (24 routes across the five resources — list plus whatever
create/toggle/rename/delete/merge each legacy top-level page actually
had). One module, not five: `REBUILD.md` decision 3's "deletable on its
own" test still holds *within* the file (nothing here imports from any
other `modules/` package, and every prior module that needed one of
these lookups had already forked its own copy rather than reaching in
here, since this module didn't exist yet), but splitting five
few-dozen-line CRUD sections into five near-empty module triples would
cost more than it buys. Two things worth recording:

1. **Five write routes now check existence and raise on an unknown id,
   where their legacy originals silently no-op'd instead** — `toggle_
   account`/`toggle_account_cashflow`, `toggle_lock` (scenarios), and
   `rename_account_level`/`delete_account_level` all ran a bare `UPDATE`/
   `DELETE ... WHERE id = %s` with no rowcount check, unlike every one of
   their conceptually-identical siblings in the same legacy file
   (`toggle_payee`, `rename_payee`, `delete_payee`, `toggle_tag`,
   `rename_tag`, `delete_tag`), which all already did check and raise.
   Read as an oversight, not a deliberate asymmetry — nothing in
   `SPEC.md`/`BACKLOG.md` calls out accounts/scenarios/account-levels as
   special here — and harmonized to match their siblings, a real
   behavior change from a verbatim port but a narrow, well-justified one
   (`repository.py`'s own docstring has the full reasoning).
2. **`merge_payees`/`merge_tags` now check the survivor id exists
   *before* repointing any FK, where legacy only ever discovered a bad
   survivor id at the very end, via the final rename's own rowcount.**
   Caught by a test, not by reading the code first — `service.
   merge_tags(conn, [999999, real_tag_id], "x")` raised a raw
   `ForeignKeyViolation` from deep inside the junction-table `INSERT`
   (before ever reaching the rowcount check), not a clean "Tag #999999
   not found," because `other_ids` in the test fixture had a real
   association to repoint. The same bug exists in legacy's own
   `merge_tags`/`merge_payees` (a plain reassignment onto a nonexistent
   id doesn't error *until* something is actually there to repoint);
   fixed here the same way `modules.imports.service.stage_import_groups`
   (Phase 1.8) already fixed an analogous "resolve it up front instead
   of relying on a constraint violation" gap for unmapped account codes.

Other decisions, smaller:

- **`_accounts_with_gaps` and `top_level_types_taken` (legacy `accounts_
  page`) are not ported** — both are rendering concerns computable by the
  frontend directly from the same flat `GET /accounts` list this module
  already returns, nothing to look up that isn't already in that
  response.
- **`TYPE_LABELS` is not ported** — a display-string mapping, not
  reference data, same "render-time, not backend" reasoning `money()`/
  `dateformat()` already got. `ACCOUNT_TYPES`/`SCENARIO_TYPES` themselves
  live in `schemas.py` as Pydantic `Literal` types instead of a plain
  list + manual membership check — a bad value is now a 422, not a
  hand-rolled `ValueError`.
- **Every write route catches `(ValueError, SQLAlchemyError)` uniformly
  as a 400, never a 404** — matching `modules/entries/`'s, `/staging/`'s,
  `/budget/`'s, and `/imports/`'s own settled convention (a "not found"
  id is client-supplied-bad-input, the same shape as any other
  validation failure, not a routing-level 404). A shared `_bad_request`
  helper in `router.py` exists because, unlike those four modules, every
  single write route here (not just some) needs the identical two-
  exception mapping.
- **No CSRF check anywhere in this module** — the one documented gap
  every prior write module carries (`modules/auth/`, Phase 1.11) that
  still applies here; narrower than it was for `entries`/`staging`/
  `imports` since nothing in this module has a user-attribution column
  to set in the first place.

89 new tests (34 `repository.py`, 27 `service.py`, 28 `router.py`) — 344
passed total. Verified for real, the same three ways as every phase
since 1.4: a full `docker compose up -d --build` (clean log, `/healthz`
200), a local `docker compose up -d db` + `pytest` run, and separately
the exact CI shape by hand (a bare `postgres:16` container, `alembic
upgrade head`, `pytest`).

**Phase 1.10 done.** `modules/scheduling/` — scheduled entries and entry
templates: `repository.py`, `schemas.py`, `service.py`, `router.py` (six
routes: list/create schedules, toggle a schedule active, list/create/
delete templates). Two lifecycles in one module, not two: a schedule
advances its own `next_date` and periodically posts a staged occurrence,
a template never posts anywhere on its own — but both are "reusable
scaffolding for a future journal entry," each only a few dozen lines,
the same "five near-empty triples would cost more than they buy"
reasoning Phase 1.9 already applied to Accounts/Scenarios/Payees/Tags.
Also added `domain/periods.py`'s `advance_date` — the one pure helper
Phase 1.1 didn't port because nothing needed it yet (`_advance_date`'s
day/week/month recurrence stepper, used only by this module).

1. **`materialize_due_schedules` is ported and fully tested, but not
   wired into anything.** Legacy runs the equivalent from its auth
   middleware, on every authenticated request, wrapped in a bare
   `try/except Exception: pass` (SPEC.md decision 9: "no task runner in
   this deployment, so auto-post on the date is done lazily here instead
   of a real cron"). Both the middleware and the session it reads are
   `modules/auth/` (Phase 1.11) concerns; wiring a periodic or
   per-request call to `service.materialize_due_schedules` into the new
   app is that phase's job, or `main.py`'s (Phase 1.14) — same "don't
   reach into a mechanism that doesn't exist yet" reasoning every prior
   module already applies to CSRF. There is deliberately no `POST
   /scheduled/materialize` route either — legacy has no explicit
   invocation path for this at all, so adding one would be inventing
   behavior, not porting it.
2. **`check_deferred_constraints` is needed here for the same real
   reason `modules/entries/repository.py`'s own docstring gives, not a
   theoretical one — and it needed the same `Connection.begin_nested()`
   SAVEPOINT-per-schedule treatment `reverse_entries_bulk` (Phase 1.5)
   already established.** `materialize_due_schedules` inserts a full
   `journal_entries` + `journal_lines` set into Staging, a real
   `enforce_balance = TRUE` scenario subject to the same `DEFERRABLE
   INITIALLY DEFERRED` balance/has-lines triggers as any manual posting.
   Legacy gets per-schedule independence for free — each occurrence is
   its own `with tx() as cur:`, committing (and so running the deferred
   check) before the next schedule's block starts; `db.get_connection()`
   gives the whole request one transaction, so without a SAVEPOINT per
   schedule, one bad schedule would silently take every schedule after
   it in the same `due` batch down too. Forked from `modules/entries/
   repository.py`, not imported — same "a module should be deletable on
   its own" test (`REBUILD.md` decision 3) every prior write module's
   own docstring already applies, alongside a fork of `modules/imports/
   repository.py`'s `staging_scenario_id`-shaped lookup.
3. **The manual `total != 0` balance check in `create_schedule`/
   `create_template` is real application logic here, not a leftover** —
   unlike `modules.entries.service.create_entry`, which leaves that
   check entirely to `journal_lines`' own deferred constraint trigger.
   `scheduled_entry_lines`/`entry_template_lines` carry no such trigger
   at all (only `CHECK (amount <> 0)` per line), so an unbalanced
   schedule or template is caught in app code or not at all, same as
   legacy.
4. **Two write routes harmonized to check-and-raise on an unknown id,
   where their legacy originals silently no-op'd** — `toggle_schedule`
   and `delete_template`, both a bare `UPDATE`/`DELETE ... WHERE id =
   %s` with no rowcount check in `app/main.py`. Same class of oversight
   Phase 1.9 already found and fixed for five of *its* routes; nothing
   in `SPEC.md`/`BACKLOG.md` singles either out as special.

Other decisions, smaller:

- **No `scenarios`/`accounts`/`payees` picker payload anywhere in this
  module's responses** — same "don't reach into a module for rendering
  convenience" reasoning every prior module applies to `modules/
  reference/`, now sharpened by one thing: `postable_accounts_by_
  scenario()`/`postable_accounts_for_pickers()` (legacy's own
  scenario-aware account-picker helpers, used by `scheduled_page`) were
  never ported into *any* module, and don't need to be — nothing here or
  in `modules/entries/` ever validates "is this account legal for that
  scenario" at write time (there is no `fn_line_account_guard`-
  equivalent trigger on `scheduled_entry_lines`/`entry_template_lines`,
  and even `journal_lines`' own version isn't pre-checked by the
  write path, just enforced by the trigger at insert). It is purely a
  combobox-filtering convenience, so it stays a frontend-only concern
  once `modules/reference/`'s plain `GET /accounts` exists.
- **`list_templates` nests each template's own `lines`/`tags` directly
  under it** — not a deviation this time, unlike `modules/entries/
  service.py`'s own contrast with legacy's three-parallel-dicts
  precursor: legacy's `templates_full()` already built this exact
  shape, so this is a straight port.
- **No CSRF check, no user-attribution equivalent** — the same
  `modules/auth/` (Phase 1.11) gap every prior write module documents,
  narrower here than for `entries`/`staging`/`imports`: neither
  `scheduled_entries` nor `entry_templates` has an attribution column at
  all, so there's nothing to leave `NULL`, just no audit trail to add.

50 new tests (16 `repository.py`, 19 `service.py`, 10 `router.py`, plus 5
new `domain/periods.py` tests for `advance_date`) — 394 passed total.
Verified for real, the same three ways as every phase since 1.4: a full
`docker compose up -d --build` (clean log, `/healthz` 200), a local
`docker compose up -d db` + `pytest` run, and separately the exact CI
shape by hand (a bare `postgres:16` container, `alembic upgrade head`,
`pytest`).

**Phase 1.11 done.** `modules/auth/` — login/logout, the session-cookie
mechanism, and the account-settings screen (username/password):
`schemas.py`, `repository.py`, `service.py`, `deps.py`, `router.py` (five
routes: `POST /login`, `POST /logout`, `GET /me`, `POST /settings/
username`, `POST /settings/password`). Ported from `app/auth.py` plus
the Auth/User settings sections of `app/main.py`, same session-cookie
design as legacy — a random opaque token in `sessions`, looked up per
request, no JWT/signing secret — REBUILD.md decision 4's "port behavior,
don't redesign it" holding here same as everywhere else.

1. **Scoped to building the mechanism, not retrofitting every prior
   write module to use it — a deliberate reading of several earlier
   modules' own docstrings, not an oversight.** `modules/entries/
   router.py` (Phase 1.5) says "Phase 1.11 wires a real dependency in
   here"; `staging`/`imports`/`budget`/`reference`/`scheduling` each
   carry a softer version of the same pointer. This phase builds
   `deps.get_current_session`/`require_csrf_header` as real, fully
   tested FastAPI dependencies any router can `Depends(...)` on — but
   does not touch entries/staging/imports/budget/reference/scheduling
   themselves. Precedent for deferring the actual retrofit rather than
   doing it here: `modules/budget/service.py`'s own Phase 1.7 docstring
   flagged "no default-scenario selection, since `modules/reference/`
   doesn't exist yet," and Phase 1.9 — the phase that built `modules/
   reference/` — did not go back and wire that default in. A module
   documenting "closeable once X exists" has consistently meant *the
   mechanism becomes available*, not *X's own phase must immediately
   retrofit every caller*. Phase 1.14 ("`main.py` cut down to app
   factory + router mounting only") is where every router is already
   being touched to be mounted for the first time — the one sensible
   place to also wire in the one dependency every write route across
   every module needs identically, rather than scattering five separate
   half-done retrofits ahead of that.
2. **The one place so far where a module is meant to be imported
   directly by its future callers, not forked.** Every prior sibling
   relationship (`staging` forking `entries`' filter builder,
   `scheduling`/`imports` forking `check_deferred_constraints`, `budget`
   forking `reports`' account queries) exists because REBUILD.md
   decision 3's "deletable on its own" test treats those as genuinely
   independent siblings. Auth isn't a sibling in that sense — every
   other module already depends, unconditionally, on there being a
   logged-in user at all (that's the entire reason `auth_gate` was
   global middleware in legacy, ahead of every route). Forking
   session-lookup/CSRF logic five times over would not preserve any real
   independence, so `deps.py`'s own docstring documents this as a
   deliberate exception, the same category `db.get_connection`/
   `errors.pg_message` already sit in: shared infrastructure, imported
   directly, not forked.
3. **`RateLimitedError`/`InvalidCredentialsError` (new) let `login`
   answer 429/401 instead of a uniform 400.** Legacy's `login_submit`
   treats a bad password and a rate-limited username identically — same
   flash-redirected login page either way, no room for a status code to
   differ. A JSON API has status codes to spend; this is a real,
   low-risk improvement the medium enables (no observable behavior
   changes for a human at a keyboard, only which numeric code a
   programmatic caller sees), not something needing its own `REBUILD.md`
   §5 entry.
4. **The CSRF token moves from a hidden form field to an `X-CSRF-Token`
   request header.** Same class of form-shape-to-JSON adaptation
   `modules.staging.schemas.MergeDuplicatesRequest`/`modules.imports`'s
   base64 round-trip already made for their own precursors, just for a
   token that travels out-of-band instead of in the body, since (unlike
   those two) every other field on a CSRF-protected request here is real
   payload and the token never was.

Other decisions, smaller:

- **`GET /me` is new, not a port.** The Jinja app never needed an
  equivalent — `request.state.user` was already in scope for every
  server-rendered template. A JSON SPA has no equivalent on page load,
  so this is the minimal "who am I, if anyone" check the architecture
  change itself requires.
- **`logout` enforces no CSRF check at all**, matching legacy's own
  `logout` exactly ("worst case of a bad token here is a no-op logout;
  just proceed") — idempotent, succeeds with no session cookie at all.
- **The single-process, in-memory login throttle (`_failed_logins`) is a
  verbatim port, deliberately, not a "fix while we're here."** Correct
  only because the deployment runs one uvicorn worker — same as legacy,
  and nothing about the rebuild changes that deployment shape.
- **`bootstrap_admin_from_env` takes its username/password as plain
  arguments, not read from `os.environ` itself** — keeps `service.py`
  framework/env-decoupled like every other module's; actually reading
  `Settings.postwarden_admin_user`/`_password` and calling this at
  startup is `main.py`'s own lifespan hook to wire, Phase 1.14, same as
  legacy's own call site.
- **No CLI equivalent to `app/cli.py`'s `create-user`/`reset-password`.**
  Out of scope for a vertical-slice module — that's a deployment tool
  invoked outside the running app, not a route; revisit at cutover if a
  fresh non-Docker install still needs a first-user bootstrap path
  beyond `POSTWARDEN_ADMIN_USER`/`_PASSWORD`.

51 new tests (10 `repository.py`, 29 `service.py`, 12 `router.py`) — 445
passed total. Verified for real, the same three ways as every phase
since 1.4: a full `docker compose up -d --build` (clean log, `/healthz`
200), a local `docker compose up -d db` + `pytest` run, and separately
the exact CI shape by hand (a bare `postgres:16` container, `alembic
upgrade head`, `pytest`).

**Phase 1.12 done.** `export/` — the shared CSV/XLSX writers, plus the
CSV/XLSX export routes on the two modules that actually need them
(`modules/reports/`, `modules/entries/`). Ported from `app/main.py`'s
~260-line shared export-plumbing block (`csv_response`, the `_xlsx_*`
style/formula helpers, `xlsx_response`) and its six `/export/*` route
pairs (Trial Balance, Balance Sheet, Income Statement, Cash Flow,
Variance, Journal), unchanged in shape — the "12 exports (812 lines)"
REBUILD.md §4 measured as the single largest "mechanical" bucket in the
old app.

1. **`export/` holds only the two files of genuinely shared plumbing —
   `csv.py` (`csv_response`) and `xlsx.py` (the style palette,
   `xlsx_data_row`/`xlsx_header_row`/`xlsx_variance_formulas`/
   `xlsx_sum_formula`/`xlsx_response`) — every report-specific and
   Journal-specific row-building function lives in a new `export.py`
   inside `modules/reports/`/`modules/entries/` themselves, not in
   `export/`.** REBUILD.md §6's tree diagram lists `export/` as one
   shared directory, but a literal reading — every export function for
   every report living in one un-scoped package — would mean `export/`
   knows the exact shape of every other module's own report/journal
   data, failing REBUILD.md decision 3's "deletable on its own" test in
   the *other* direction: deleting `modules/reports/` should not require
   also editing a shared `export/` file that has no reason to know
   Income Statement exists. `export/` stays exactly as generic as
   `csv.writer`/`openpyxl` themselves — "write this cell with this
   style" — and each module's own `export.py` is where "here is what an
   Income Statement row/Journal leg becomes on a spreadsheet" lives,
   same vertical-slice boundary every prior module already draws for its
   own `service.py`/`repository.py` split.
2. **Every `_xlsx_*` helper drops its leading underscore.** Legacy's
   functions were private to one 5,908-line file; here the module
   boundary (`export.xlsx`) *is* the privacy boundary, and two other
   modules are meant to import these directly — the same "shared
   infrastructure, imported not forked" exception `modules/auth/deps.py`
   (Phase 1.11) already established, extended here to a second case.
3. **The CSV/XLSX export routes deliberately do NOT apply the read
   route's own "blank date range defaults to the current month" step**
   — ported forward from `income_statement_export_csv`/`cash_flow_
   export_csv`'s own established legacy behavior: a blank `date_from`/
   `date_to` on an export means unbounded, not "this month." A real, if
   easy-to-miss, page-vs-export difference that predates this rebuild
   and is preserved rather than "fixed" (REBUILD.md decision 4).
   `modules/reports/router.py`'s own module docstring calls this out so
   it doesn't read as an oversight later.
4. **Every account row's own base/compare figure in an XLSX export
   stays a literal, never a `SUM()` over a row range** — a rolled-up
   multi-level account tree would silently double-count under a range.
   Only cell-by-cell references are ever live formulas (Variance/%
   Variance pairs, Income Statement's "Net income after X" running
   rows) — each one names its own row's cells individually
   (`xlsx.xlsx_sum_formula`/`xlsx_variance_formulas`), the exact same
   safety property legacy's own comments on this called a hard
   requirement, not a style choice.

Other decisions, smaller:

- **Reports' export routes are mounted as `.csv`/`.xlsx` siblings under
  the existing `/reports/<name>` path** (`GET /reports/trial-balance.csv`),
  not legacy's flat top-level `/export/<name>.csv` namespace — natural
  once `modules/reports/router.py` already owns the `/reports` prefix;
  the Journal's own export keeps legacy's exact path shape instead
  (`GET /entries/export.csv`) since that already equals `/entries` +
  `/export.csv`, no renaming needed.
- **`modules/entries/repository.py` gained one function,
  `export_rows`**, and `service.py` gained the thin `export_rows`
  wrapper around it (mirroring `list_entries`'s own `build_filter` ->
  repository call shape) — same filters, same `WHERE` clause
  `list_entries` uses, just no pagination and, optionally
  (`group_legs=True`), debits-before-credits ordering for the XLSX
  export's traditional general-journal presentation instead of
  `line_no`'s original posting order.
- **`modules/reports/export.py`'s income-statement functions branch on
  `"periods" in result`** (present only in a `income_statement_matrix`
  result) rather than taking an extra `is_split` flag — the two
  service functions' return shapes already disambiguate themselves, so
  a caller (`router.py`) never has to pass along which one it called.

47 new tests (13 in `export/` itself — `test_csv.py`/`test_xlsx.py`, pure
unit tests with no database; 14 in `modules/reports/test_export.py`
plus 5 export-route smoke tests added to its own `test_router.py`; 9 in
a new `modules/entries/test_export.py` plus 2 each added to `entries/
test_repository.py`/`test_service.py`/`test_router.py`) — 492 passed
total. Verified for real, the same three ways as every phase since 1.4:
a full `docker compose up -d --build` (clean log, `/healthz` 200), a
local `docker compose up -d db` + `pytest` run, and separately the exact
CI shape by hand (a bare `postgres:16` container, `alembic upgrade
head`, `pytest`).

**Phase 1.13 done.** `analytics/` — the star-schema views plus the
documented `/api/*` contract: `repository.py`, `service.py`, `router.py`
(five read-only `/api/*` routes — trial-balance, accounts, scenarios,
entries, monthly-activity — plus two Connect BI settings routes). Ported
from `app/main.py`'s JSON-API section (its final block, five routes) and
its `/settings/connect-bi`/`/settings/connect-bi/download.pbids` routes.
The smallest module so far — no writes, no CSRF, nothing from
`modules/auth/` to wire in — but two decisions worth recording:

1. **Every query is its own fork, not an import — cutting in both
   directions at once, not just the usual sibling-module direction.**
   `repository.accounts` (`SELECT * FROM v_dim_account ORDER BY
   sort_path`, no `WHERE is_active`) looks almost identical to
   `modules/reports/repository.dim_accounts`, and `repository.scenarios`
   looks almost identical to `modules/reference/repository.scenarios_all`
   — but neither pair was ever actually the same query: legacy's own
   `api_accounts` never filtered to active accounts at all (a JSON
   mirror for a BI tool has a reason to see an archived account that a
   report/picker doesn't), and reports' own scenario lookup
   (`full_scenarios`) is deliberately narrower than the reference/`/api/*`
   shape, not a different version of the same thing. REBUILD.md decision
   3's "deletable on its own" test settles it the same way it has every
   prior time: `modules/reports/`, `modules/reference/`, and `analytics/`
   should each survive the others being deleted.
2. **The two Connect BI routes (`GET /settings/connect-bi`, `GET
   /settings/connect-bi/download.pbids`) landed here, not in a Settings
   module that doesn't exist and isn't in REBUILD.md §6's roadmap.**
   Legacy's `/settings` (theme/amount-entry/number-format) and
   `/settings/account` (username/password, Phase 1.11) are pure
   client-side-state or already-ported-elsewhere pages with nothing left
   to build on the backend; Connect BI is the one `/settings/*` legacy
   route with real logic (host/port resolution, the `BI_OBJECTS`
   catalog, the `.pbids` file body), and everything it describes — the
   four star-schema views and the one SRF a BI tool can actually query —
   is exactly what this module already owns. `service.py`'s own
   docstring has the full reasoning; `config.py`'s `postwarden_bi_port`
   field (added ahead of time back in Phase 1.2, unused until now) was
   the tell that this was always where it was headed.

Other decisions, smaller:

- **No `schemas.py`** — same reasoning `modules/reports/router.py`
  (Phase 1.4) already gives: every route is a GET with plain query
  params, no request body ever needs a Pydantic model.
- **No single router `prefix`** — the `/api/*` and `/settings/*` route
  families don't share one, so every route spells out its own full
  path, the same shape `modules/reference/router.py` and `modules/auth/
  router.py` already use for the identical reason (bundling more than
  one legacy top-level concern into one module).
- **`repository.trial_balance` exposes only `(scenario, as_of)`, not
  `fn_trial_balance`'s full `(scenario, as_of, from)` signature** —
  legacy's own `api_trial_balance` never accepted a `from` either; this
  module ports what `/api/*` actually did, not the SRF's full capability.

24 new tests (11 `repository.py`, 4 `service.py` — the `/api/*` wrappers
are thin pass-throughs already covered by `repository.py`'s own tests,
so these focus on `connect_bi_info`/`pbids_document`, the two functions
with real logic — 9 `router.py`) — 513 passed total. `backend/tests/
analytics/conftest.py`'s own `book` fixture forks `modules/reports/
conftest.py`'s (same "deletable on its own" reasoning as the module
itself), extended with a second scenario and an inactive account so
`entry_count`/`base_level_name`/the no-`is_active`-filter behavior all
have something to actually prove. Verified for real, the same three ways
as every phase since 1.4: a full `docker compose up -d --build` (clean
log, `/healthz` 200), a local `docker compose up -d db` + `pytest` run,
and separately the exact CI shape by hand (a bare `postgres:16`
container, `alembic upgrade head`, `pytest`).

**Phase 1.14 done.** `main.py` — every module's router mounted into the
real `app` for the first time (`reports`, `entries`, `staging`,
`imports`, `budget`, `reference`, `scheduling`, `auth`, `analytics`),
plus the two retrofits every one of those modules' own docstrings had
been pointing at since the phase that built them: the `modules/auth/`
(Phase 1.11) session/CSRF gate, and `bootstrap_admin_from_env`'s actual
call site.

1. **The auth retrofit is a router-level `Depends(...)`, not global
   middleware — `modules/auth/deps.py`'s own Phase 1.11 docstring already
   settled this ("as a per-route dependency instead of blanket
   middleware"), this phase just carried it out.** Every module's
   `router = APIRouter(...)` gained `dependencies=[Depends(get_current_
   session)]` — the direct equivalent of legacy's global `auth_gate`
   requiring a valid session for every route, just FastAPI-idiomatic
   (visible in the router's own construction, testable by overriding one
   named dependency) instead of ASGI-idiomatic (an opaque `call_next`
   wrapper). Every write route additionally depends on `require_csrf_
   header`. Two shapes, depending on whether the route's own service call
   has anywhere to put a real user id:
   - **`modules/entries/`'s `create_entry`/`reverse_entry`/`reverse_
     entries_bulk`, `modules/staging/`'s `approve_entries`, and `modules/
     imports/`'s `import_csv`/`import_mapped_commit`** bind the
     dependency to a real `session: dict` parameter and thread `session
     ["user_id"]` through to `created_by_user_id`/`imported_by_user_id`
     — columns every one of those `service.py`/`repository.py` functions
     already accepted as an optional argument since the phase that built
     them (Phase 1.5, 1.8, 1.9), left `None` until now on purpose.
   - **Every other write route** — all of `modules/reference/`,
     `modules/scheduling/`, `modules/budget/`'s `save_cell`, and
     `modules/entries/`'s tag/description/memo edits — has nothing to
     attribute (no user-attribution column on that table at all, or the
     edit itself never touched one in legacy either), so it gains
     `require_csrf_header` as a bare `dependencies=[...]` entry on the
     route decorator instead of a bound parameter.
   `modules/auth/router.py` itself carries no router-level dependency:
   `/login` has to stay reachable with no session at all, and its other
   four routes (`logout`, `me`, the two `/settings/*` routes) already
   spelled out their own per-route `Depends(...)` back in Phase 1.11.
2. **One piece of legacy's `auth_gate` doesn't fit a per-route
   dependency at all, and stays real middleware in `main.py`:
   `advance_due_schedules`, lazily materializing due schedules on every
   request that carries a valid session** (SPEC.md decision 9 — no task
   runner in this deployment). No single module's router can own
   something that has to run on literally every request regardless of
   which module it's headed to, so `main.py` is where it lives, exactly
   the cross-cutting exception `modules/scheduling/service.py`'s own
   Phase 1.10 docstring predicted ("wiring a periodic or per-request call
   ... into the new app is that phase's job, or `main.py`'s"). Opens its
   own connection directly against `get_engine()` rather than going
   through `db.get_connection()`, since it runs outside any route's own
   request-scoped dependency graph; swallows any failure the same bare
   `except Exception: pass` legacy uses.
3. **`main.py`'s `lifespan` calls `auth.service.bootstrap_admin_from_
   env` with `settings.postwarden_admin_user`/`_password`** — the one
   remaining piece of legacy's own `lifespan`, same call site. **Does
   NOT call anything migration-related**, unlike legacy's `lifespan`
   calling `run_migrations()`: REBUILD.md decision 5 already made Alembic
   a separate, explicit step (the Dockerfile's own `CMD`, or CI's own
   `alembic upgrade head`) that runs *before* this process starts, not
   from inside the app — `main.py`'s own docstring calls this out so it
   doesn't read as a gap.
4. **Caught by this phase's own new test, not by inspection**:
   `analytics/router.py` was the one module whose Phase 1.13 write-up
   already listed a settled auth stance but whose actual `router =
   APIRouter(...)` line was never updated to carry it — every other
   module's `router.py` got the `dependencies=[Depends(get_current_
   session)]` treatment directly during this phase's own pass, but
   analytics' pass only touched its test file's own override, leaving
   the real router still wide open. `test_main.py`'s `test_analytics_
   api_route_401s_with_no_session` (below) caught this immediately — a
   `200` where every other protected route answered `401` — fixed in the
   same commit, not a follow-up.

Other decisions, smaller:

- **A new `mk_user` helper in `backend/tests/conftest.py`.** The three
  modules that now thread a real `session["user_id"]` into a real FK
  (`created_by_user_id`/`imported_by_user_id`) need an actual `users`
  row to point at in their own scratch-DB tests — a bare made-up int
  like `1` violates the FK in a database that starts with no seeded
  users at all. Random username per call (`users.username` is UNIQUE),
  since some existing tests already call `client_for(conn)` more than
  once within a single test.
- **Every module's own `test_router.py` `client_for()` now overrides
  `get_current_session` (and `require_csrf_header`, for the modules with
  write routes) to a fixed fake session**, the same "override the
  dependency directly rather than simulate a real login" shape `test_
  service.py` already used for `get_settings` back in Phase 1.13 —
  simpler and faster than a real login/CSRF-token round-trip in every
  one of the ~500 existing tests this phase's own router changes would
  otherwise have 401'd.
- **A new `backend/tests/test_main.py`, testing `main.py` itself for the
  first time** — nothing before this phase exercised the real, fully-
  mounted `app` object; every module's own tests proved their router
  *in isolation*. Covers: every module actually being mounted (one
  representative path each, via `app.openapi()`), the auth wiring
  holding through the real `app` (a handful of `401` checks, using the
  real `app`'s own `get_connection` override pointed at this test's
  scratch transaction — not a second throwaway `FastAPI()`, since the
  point is proving `main.py` itself, not re-proving each module), and
  `advance_due_schedules`/`lifespan` in isolation via a fake `Engine`
  and `monkeypatch.setattr` on `main.auth_service`/`main.scheduling_
  service` directly — deliberately not a real Postgres connection for
  those two, since `bootstrap_admin_from_env`'s and `materialize_due_
  schedules`' own logic already have real-Postgres tests in `modules/
  auth/`'s and `modules/scheduling/`'s own suites (Phases 1.11, 1.10),
  and the *only* new thing to prove here is `main.py`'s own plumbing
  ("call this, with these arguments, only under these conditions") —
  which also sidesteps a real hazard: the actual, cached `get_engine()`
  points at whatever `DATABASE_URL` names, which for a developer running
  this suite locally is their own `docker compose up -d db` database,
  not the scratch one `conftest.py` builds — a test that let `lifespan`
  or the middleware touch it for real would leave a stray admin user or
  materialized schedule in a developer's own dev data on every `pytest`
  run.
- **Verified for real, end to end, against the actual running
  container** — not just the pytest suite: `docker compose up -d
  --build`, manually bootstrapped an admin user against the live `db`
  service, then round-tripped `POST /login` → `GET /reports/trial-
  balance` (200) → `POST /tags` with no `X-CSRF-Token` header (400, the
  exact "session expired or stale" message) → the same request with the
  header (201) → `POST /entries` → confirmed the new entry's own
  `created_by_user_id` resolves to the logged-in username via a direct
  `psql` join. This is the first phase where that kind of check is even
  possible — every prior module's routes existed but were never reachable
  through the real app until this one mounted them.

10 new tests (`test_main.py`) — 523 passed total. Verified for real, the
same three ways as every phase since 1.4: a full `docker compose up -d
--build` (clean log, `/healthz` 200, plus the manual end-to-end
login/CSRF/attribution check above), a local `docker compose up -d db` +
`pytest` run, and separately the exact CI shape by hand (a bare
`postgres:16` container, `alembic upgrade head`, `pytest`).

**Phase 1.15 done.** The gate: `db/schema.sql` was never touched by
Phase 1 (REBUILD.md §3's central premise, restated in `REBUILD_STATUS
.md`'s own header every phase since), so the 60 pure-Postgres tests
were never expected to need a code change — this phase is about
actually *confirming* that, and confirming it the way that counts.

- **Ran `tests/test_invariants.py` + `tests/test_cashflow.py` against
  the current schema — 60 passed, unchanged**, no edits to either file.
  Run against `backend/docker-compose.yml`'s own `db` service
  (localhost:5433, same `db/schema.sql` it always loads), with
  `POSTWARDEN_TEST_ADMIN_URL`/`POSTWARDEN_TEST_URL` pointed at it —
  `tests/conftest.py` doesn't care which Postgres it talks to, so no new
  fixture or database was needed.
- **A real finding, not a formality: `rebuild` had never been pushed to
  `origin`.** All of Phase 1 (19 commits, 1.5 through 1.14) existed only
  on this machine — every "verified against CI's exact shape by hand"
  note in this file's own log through Phase 1.14 was a bare
  `postgres:16` + `alembic upgrade head` + `pytest` run reproducing
  CI's *steps*, never an actual GitHub Actions run. "Every ported
  module's own tests are green in CI" cannot be true of a CI that has
  never executed, so closing this gate meant pushing the branch for the
  first time — safe and expected per `CLAUDE.md`'s own branch-discipline
  section (`notify-postwarden-public.yml` fires on `master` pushes
  specifically; pushing `rebuild` triggers nothing deploy-shaped, only
  `backend-ci.yml`).
- **A second real gap, found by checking rather than assuming: the 60
  pure-Postgres tests had zero CI coverage at all, on any branch.**
  `master` has no CI (REBUILD.md §6, Phase 0.5's own framing), and
  `backend-ci.yml` — added on this branch — was scoped to `backend/`
  paths only, so it never touched root `tests/`. A safety net that only
  ever runs by hand isn't continuously gating anything; REBUILD.md §3
  calls these tests "the safety net" specifically because they're
  supposed to hold with no code path around them, and "runs when a human
  remembers to" is exactly the kind of code path around them that
  framing is meant to rule out. Fixed by adding a second job,
  `invariants`, to `backend-ci.yml` (own Postgres service container,
  deliberately not a step in the existing `test` job — these tests apply
  `db/schema.sql` directly via `tests/conftest.py`'s own raw `CREATE
  DATABASE` + SQL-file load, not through Alembic like the backend's own
  migrated database, and one Postgres instance serving two different
  schema-provisioning paths would be confusing for no benefit). Only
  `psycopg`/`pytest` installed, not `backend`'s own package or
  `requirements-dev.txt`'s full legacy-app dependency set — neither test
  file imports either. `tests/**` added to both workflows' trigger
  paths, the same reasoning `db/schema.sql` was already there for.
- **Pushed, and both jobs went green on the first real run** —
  `invariants`: 60 passed in 1.11s; `test`: 523 passed in 24.98s
  (`gh run view` on the actual run, not a local reproduction). This is
  the first GitHub Actions run of any kind this branch has ever had; it
  passing on the first attempt is confirmation, not luck — the "bare
  `postgres:16`, `alembic upgrade head`, `pytest`" hand-verification
  done at the end of every phase since 1.4 was accurately reproducing
  CI's actual shape all along, it just hadn't been checked against the
  real thing until now.
- No module code changed in this phase — this was a verification +
  CI-coverage gate, not a port. `main.py` and every `modules/*/router.py`
  are exactly as Phase 1.14 left them.

**Phase 1 is done.** Every module from `domain/` through `main.py` is
built, tested, mounted, and now provably green in real CI alongside the
60 pure-Postgres tests it was always supposed to sit beside.

**Phase 2.1 in progress.** `frontend/` — a Vite + React + TypeScript
scaffold (`npm create vite@latest -- --template react-ts`), stripped of the
template's own demo content (the counter, the React/Vite logos, the
docs/social links) down to a placeholder `App.tsx`: a heading and a live
`/healthz` check, the same "prove the pipeline, not the feature" role
Phase 0's own trivial `/healthz` route played for the backend. Real UI
(the shell, the CSS tokens, real screens) is Phase 2.3 onward, not this
item.

1. **`vite.config.ts`'s own `build.outDir` points straight at `backend/
   src/postwarden/static/`, not this project's own `dist/`.** Deliberate:
   `main.py` now mounts that exact path via `StaticFiles` if present
   (`config.py`'s new `postwarden_static_dir` setting, defaulting to
   `Path(__file__).resolve().parent / "static"`), and pointing the build
   there directly means a plain local `npm run build` followed by a plain
   `uvicorn postwarden.main:app` serves the SPA with zero copy step, and
   `backend/Dockerfile`'s own multi-stage build (below) copies to the
   identical relative spot — one convention, not a build-tool one and a
   deploy one that happen to agree.
2. **The static mount is registered last, and only if the directory
   exists.** *Last*, because several module routers already own a path a
   future client-side route will also want — `GET /entries` is the
   Journal's own JSON data route today, and Starlette matches routes in
   registration order, so a mount added after it can only ever answer a
   request no router already claimed. *Only if it exists*, so a
   backend-only checkout (CI, any module's own test suite, a developer who
   hasn't run `npm run build` yet) is unaffected — confirmed, not assumed:
   the full 523-test backend suite passes unchanged with the directory
   present (built during this same phase) precisely because the mount
   only adds routes no existing test path collides with.
3. **A real, open gap, documented rather than quietly deferred:
   deep-link/refresh support for the SPA's own future client-side routes
   is not solved here.** `StaticFiles(..., html=True)` serves `/` and
   every hashed `/assets/...` file, which is everything this phase's own
   placeholder page needs — but it does not fall back to `index.html` for
   an arbitrary unmatched path the way a real SPA router needs for a
   direct browser navigation or refresh. Worse, several of the paths a
   future client router will want (`/entries`, `/reports/trial-balance`,
   `/staging`, ...) are already real backend JSON routes at that exact
   path, so even a working fallback wouldn't reach them — the app-shell
   HTML and the JSON API currently share a path namespace. Solving this
   means deciding how those two stop colliding (an `/api` prefix on the
   data routes being the obvious shape, but that is a real, cross-module
   decision, not something to improvise inside a static-file mount) —
   deferred to whichever phase actually wires in a client-side router
   (Phase 2.4's shell, or Phase 3's own archetype screens), the same
   "don't reach into a mechanism that doesn't exist yet" reasoning every
   prior phase already applied to CSRF/attribution/default-scenario
   lookups.
4. **`backend/Dockerfile` is now two stages — a `node:22-slim` builder,
   discarded before the final image — and `backend/docker-compose.yml`'s
   `build.context` moved from `backend/` to the repo root** (`dockerfile:
   backend/Dockerfile` still points at this file; a `backend/`-scoped
   context can't reach `../frontend` for the builder stage's own `COPY`).
   The builder stage's `WORKDIR` is `/repo`, deliberately mirroring the
   real repo's own root layout (`frontend/` and `backend/` as siblings),
   so `vite.config.ts`'s `outDir: '../backend/src/postwarden/static'`
   resolves to the same legible path inside the image that it does on a
   real checkout, rather than an absolute path a reader would have to
   trace through a relative `..` to understand.

**Verified for real, partially — the Docker step is the one open item.**
`npm install` + `npm run build` (a real `vite build`, not a dry run)
produced exactly the files `config.py`'s new setting expects, in the
expected place; a real `uvicorn postwarden.main:app` (no Docker) then
served `/` (200, the built `index.html`), a real hashed `/assets/*.js`
file (200), `/favicon.svg` (200, ported from `app/static/icon.svg` rather
than left as Vite's own default logo), and confirmed `/reports/
trial-balance` still answers `401` unauthenticated — the static mount does
not shadow the API. The full backend test suite (523 tests) passes
unchanged with the built directory present. **`docker compose up -d
--build` itself could not be completed this session**: pulling
`node:22-slim` inside this sandboxed environment's Docker daemon fails
immediately and reproducibly (`DeadlineExceeded: context deadline
exceeded` on the image-metadata fetch, confirmed on three separate
attempts, including one at a 10-minute timeout with no progress — and a
plain `docker pull hello-world`, the smallest image that exists, hangs the
same way), while `python:3.12-slim` and `postgres:16` — both already
pulled in earlier phases — resolve instantly. This reads as a sandbox-level
registry restriction on *new* image pulls specific to this session, not a
problem with the Dockerfile or compose changes themselves: `curl`/`npm`
from the same shell reach the public internet fine, and this exact
`docker compose up -d --build` pattern is this project's own established,
working local-dev loop on this machine outside this session (per
`~/GitHub/CLAUDE.md`'s "local dev loop" notes). **Needs a real run on this
machine outside the sandbox (or in CI) to close out** — flagged rather than
skipped silently; see the Open questions section.

**Phase 2.2 done.** A typed API client, generated from the backend's own
OpenAPI schema rather than hand-written — `backend/scripts/
dump_openapi_schema.py` (new: imports `postwarden.main` directly and
calls `app.openapi()`, needing no `DATABASE_URL`/Postgres/Docker at all,
since `db.get_engine()` is lazy) feeds `openapi-typescript` to produce
`frontend/src/api/schema.ts` (4553 lines, 72 paths), which `frontend/src/
api/client.ts` wraps in a single `openapi-fetch` client every screen will
import instead of hand-rolling its own `fetch(...)` calls. `App.tsx`'s
placeholder `/healthz` check now goes through `client.GET(...)` instead
of a bare `fetch`, specifically so the existing pipeline proves the new
client actually works, not just that it compiles.

1. **`openapi-fetch` + `openapi-typescript`, not a full SDK generator
   (`openapi-typescript-codegen`, `orval`).** The latter emit one
   generated function per route plus their own request machinery; the
   former is types-only codegen (`schema.ts`) plus a ~6&nbsp;kB typed
   wrapper around the platform `fetch`, in keeping with this rebuild's
   existing minimalism (no heavy framework adopted without a concrete
   need for it) and because this project's own request/response shapes
   are already simple enough (plain dicts, no pagination envelopes, no
   nested resource expansion) that a generated SDK layer would be
   ceremony, not value.
2. **Request bodies come out fully typed; response bodies mostly come out
   as `{ [key: string]: unknown }`, and that's accepted, not treated as a
   gap to close here.** `entries/schemas.py`'s own docstring already
   settled "response shapes stay plain dicts" as a deliberate Phase 1
   decision — every route returns `-> dict`/`-> list[dict]`, not a
   Pydantic response model, so there is nothing more specific in the
   OpenAPI schema for the generator to describe. `--empty-objects-unknown`
   (in the new `generate:api` script) is what keeps that `unknown` rather
   than openapi-typescript's default `Record<string, never>`, which would
   have (incorrectly) typed every response as an object with no keys at
   all — confirmed by diffing generated output with/without the flag; it
   only changes one thing, `HTTPValidationError.ctx` (FastAPI's own
   built-in error detail, not one of this app's routes), the same class of
   improvement everywhere else too. Giving every route its own real
   Pydantic response model would be a substantial, separate undertaking
   spanning every module — explicitly out of scope for "add a client,"
   the same "don't reach into a mechanism that doesn't exist yet"
   reasoning this file already applies elsewhere.
3. **`schema.ts` is committed, not gitignored, even though it's
   generated.** `backend/Dockerfile`'s frontend-build stage (Phase 2.1)
   runs on bare `node:22-slim` with no Python at all, so nothing in that
   build can regenerate it — unlike the built `static/` output itself,
   which *is* gitignored because every build path (local, Docker)
   regenerates it fresh. Regenerating `schema.ts` and committing the diff
   is a deliberate developer step, same spirit as Alembic migrations
   being explicit rather than automatic (REBUILD.md decision 5). Nothing
   enforces freshness automatically yet; `openapi-typescript --check`
   exists for a future CI step if drift turns out to be a real problem in
   practice, not added preemptively here.
4. **CSRF-header attachment is deliberately not wired into the client
   yet.** `modules/auth/deps.py`'s `require_csrf_header` needs an
   `X-CSRF-Token` header on every write, sourced from the current
   session — and there is no session/auth state anywhere in the frontend
   yet (Phase 3's login screen is what will create one).
   `client.ts`'s own comment names `openapi-fetch`'s `use()` middleware
   hook as the obvious place to add it once that state exists, rather
   than improvising a place to read a token from now.

**Verified for real.** `npm run generate:api` ran for real against the
real backend (no mocked/hand-written schema) and produced real output;
spot-checked request bodies (`CreateEntryRequest` etc. — full field
lists, docstrings, the `interval_unit` enum) and response bodies
(`healthz`'s concrete `dict[str, str]` came out as `{[key: string]:
string}`; a bare `-> dict` route came out as `{[key: string]: unknown}`)
by reading the generated file directly, not just trusting the tool ran.
`npm run build` (`tsc -b && vite build`) passes with zero type errors,
meaning `client.ts` + `schema.ts` + `App.tsx`'s new `client.GET(...)`
call all type-check together against the real generated `paths` type. The
full backend test suite (523 tests) stays green, unaffected, as expected
for frontend-only work. A real `uvicorn postwarden.main:app` (no Docker,
same constraint as 2.1) served the rebuilt bundle: `GET /` 200, `GET
/healthz` 200 with the expected JSON, and the built, minified JS bundle
itself contains the literal `/healthz` call, confirming the typed client
actually made it into the shipped bundle. **Not verified**: an actual
browser rendering the page and showing "Backend: ok" in the live DOM —
no browser tool is available in this session, the same gap 2.1's own
verification had (that check has always been curl-level, not
browser-level, in this environment) — and the Docker build itself, for
the same sandbox reason already tracked from 2.1 (see Open questions);
2.2 adds two new npm dependencies (`openapi-fetch`, `openapi-typescript`)
the Docker build's frontend-build stage would need to `npm ci`, untested
either way, but this doesn't change the nature of the existing gap since
that stage already couldn't be exercised at all this session.

**Phase 2.3 done.** `frontend/src/index.css` — the 320 CSS custom
properties (the default Slate palette plus its 21 `data-theme` variants)
and the 3 `data-font` bundles, ported byte-for-byte from `app/static/
style.css`'s own first 565 lines. The placeholder scaffold's own comment
("the real 327 CSS custom properties and 21 themes ... land in Phase
2.3 — deliberately not here, since this file predates any of that work")
already named this file as the destination.

1. **Cut point verified structurally, not just by eye.** `app/static/
   style.css` is 2,145 lines total, but a full-file scan for `--*:`
   declarations found all 320 of them inside the first 565 lines — the
   `-- top bar --` comment at line 566 is exactly where the source
   itself turns from tokens to components, so nothing past that line
   needed porting for this phase; a script diff also confirms the ported
   565 lines are byte-identical to the source, not retyped.
2. **The scaffold's own `color-scheme: light dark` reset (from Vite's
   template, not from legacy) was dropped, not carried forward.** Legacy
   never sets it anywhere in `style.css`/`base.html`, and it actively
   fights this app's own manual `data-theme` mechanism — a browser
   honoring `light dark` styles native form controls (scrollbars,
   checkboxes) off the OS preference regardless of which of the 21
   explicit themes is actually active, the opposite of what picking a
   theme is for.

**Verified for real, further than looked possible at the start of this
session.** This environment had no `npm`/`node` on `PATH` at all
initially (a new, narrower gap than the Docker one tracked since Phase
2.1 — confirmed still separately true this session too, see below) and
no already-built frontend running anywhere. Network access itself is
fine (only the Docker daemon's own registry pulls are restricted here),
so a portable Node 22 binary was downloaded directly and used for a real
`npm run build` — clean, `tsc -b && vite build`, CSS bundled to 6.82 kB.
Separately, `backend-db-1` (a `postgres:16` container from `backend/
docker-compose.yml`'s own `db` service) turned out to already be running
healthy from an earlier session — pointing a real `uvicorn postwarden.
main:app` at it directly (no Docker) let `lifespan` succeed for the
first time this session (`bootstrap_admin_from_env` against a real
Postgres, not skipped): `GET /` and `/healthz` both 200, and the served
CSS asset came back `content-type: text/css`, inspected over real HTTP
— 21 `data-theme` blocks, 22 `--accent` declarations (default + 21), and
the Matrix theme's own minified block matches the source exactly
(`--paper:#000` etc., `#000000` minified losslessly). **Not verified**:
an actual browser rendering a themed page — no browser tool exists in
this session, the same gap 2.1/2.2 already carried, just never
exercised until a UI change (this one) made it relevant. Tracked in Open
questions alongside the Docker gap rather than treated as blocking this
phase: the correctness risk of a byte-identical port of already-shipped,
already-designed values is low, and both gaps get closed by the same
kind of real run once available.

**Phase 2.4 done.** `frontend/src/shell/` — `Shell.tsx`, `Sidebar.tsx`,
`Topbar.tsx`, `FlashBanner.tsx`, `nav.ts`, `useSidebarPin.ts`,
`useSidebarGroupCollapse.ts` — plus the pre-paint restore script, moved
from `app/templates/base.html`'s own inline `<head>` script into
`frontend/index.html` directly, unchanged. `frontend/src/index.css`
gained 269 more lines (844 total) — four more byte-for-byte ranges from
`app/static/style.css` (top bar/hamburger sidebar/footer, flash messages,
the shared chevron, the 720px/reduced-motion rules), the same porting
discipline Phase 2.3 established for the tokens. `App.tsx` now renders
its existing placeholder content inside `<Shell>`.

1. **Four separate byte ranges, not one contiguous cut — verified the
   same structural way Phase 2.3 verified its own single cut point.**
   Unlike the tokens (one clean prefix), the source file interleaves
   shell sections with page-specific ones that belong to later phases:
   lines 566–732 (top bar, hamburger sidebar, `--content-max`/`main`/
   `.footer`), 853–877 (flash messages), 1610–1637 (the chevron shared by
   the sidebar, date picker, tree collapse, and number stepper — needed
   here because the sidebar's own collapse indicator uses it), and
   2113–2145 (the ≤720px breakpoint and the `prefers-reduced-motion`
   transition rule). Deliberately skipped in between: 734–852 (the
   login split-screen and demo callout — a real different phase,
   Phase 3.1, not just "some selectors don't exist yet") and 878–1609
   (the ledger table, forms, combobox — later archetype work). A Python
   script diffed all four extracted ranges against `index.css`'s own
   appended copy line-for-line; all four came back byte-identical.
2. **The 720px and reduced-motion rules were ported whole, including
   selectors for components that don't exist in the frontend yet**
   (`.entry-journal summary`, `table.ledger`, `.panel`, `details.entry`,
   `.balance-bar`) — the same call already made for most of Phase 2.3's
   21 themes, most of which also serve components not yet built. A CSS
   selector matching nothing is inert, not fragile; splitting a single
   source rule to strip the not-yet-relevant part of its own selector
   list would only mean re-adding it later, by hand, when that component
   ships — a real chance to introduce a typo Phase 2.3's own byte-diff
   verification exists to rule out.
3. **`user` is a plain nullable prop through `Shell`/`Topbar`/`Sidebar`,
   not read from any real session — there is no session anywhere in the
   frontend yet.** Matches legacy's own `{% if request.state.user %}`
   guard exactly: with `user={null}`, only the topbar's left half, the
   flash slot, and the footer render — no hamburger, no sidebar, no
   username/logout. `App.tsx` currently passes a hardcoded
   `PLACEHOLDER_USER = { username: 'david' }`, commented as temporary,
   purely so this phase's own shell has something to be verified
   against; Phase 3.1 (login) is what replaces it with real state, and
   nothing in `Shell.tsx`/`Topbar.tsx`/`Sidebar.tsx` needs to change when
   that happens, since they already only depend on the shape of `user`,
   never its source. Same "don't reach into a mechanism that doesn't
   exist yet" reasoning every backend module already applied to auth/
   CSRF ahead of Phase 1.11, and the same accepted-fake-value pattern
   Phase 1.11's own `test_router.py`'s `client_for()` established for a
   test session ahead of the real thing.
4. **Logout is a plain `<button onClick>`, not legacy's `<form
   method="post" action="/logout">`.** A real form submit is a full-page
   navigation — wrong for a SPA. `onLogout` is an optional prop, unwired
   for the same reason #3 already gives: `POST /logout` needs an
   `X-CSRF-Token` sourced from a real session, and there isn't one yet.
5. **The pin/hover-preview mechanics (`useSidebarPin.ts`) write
   `sidebar-pinned` straight to `document.documentElement.classList`,
   the same way `sidebar.js` did, rather than letting React own the
   class through some wrapper element's own `className`.** There is no
   wrapper element positioned to hold it — `index.html`'s own pre-paint
   script already established `document.documentElement` as the single
   source of truth for that class before React ever mounts, and several
   CSS rules key off `html.sidebar-pinned` globally (`.topbar-inner`,
   `main`, `.footer`), not just the sidebar's own subtree. The
   open/close and per-group collapse state, by contrast, stay ordinary
   React state — nothing outside each component's own subtree needs to
   read those.
6. **No footer version number** (`"PostWarden v{{ version }}"` in
   legacy, reading the repo-root `VERSION` file at template-render time)
   — no backend route exposes it anywhere the frontend can reach yet.
   Genuinely out of this phase's own scope (sidebar/topbar/flash/
   pre-paint script, per this file's own checklist wording); the obvious
   real fix — piggyback it on a route that already needs to exist, e.g.
   Phase 3.1's own `GET /me` — doesn't exist yet either.
7. **One real lint finding, fixed during this phase, not deferred.**
   `oxlint`'s `react(set-state-in-effect)` rule caught
   `FlashBanner.tsx`'s first draft — it read `window.location.search` and
   called `setState` inside a `useEffect`, which the linter correctly
   flags as an unnecessary extra render (nothing ongoing to synchronize
   with yet, since no client-side router re-renders this component
   across a navigation). Fixed by deriving the value once via
   `useState`'s own lazy initializer instead — `npm run lint` came back
   clean afterward.

**Verified for real, the same way as Phase 2.3.** A real `npm run build`
(`tsc -b && vite build`, zero type errors) and a real `npm run lint`
(`oxlint`, zero warnings after the fix above) both pass. A real `uvicorn
postwarden.main:app` (against `backend-db-1`, the same already-running
`postgres:16` container Phase 2.3 used) served the rebuilt bundle end to
end: `GET /` 200 with the pre-paint `<script>` confirmed sitting ahead of
both the injected `<link rel="stylesheet">` and the deferred `type=
"module"` bundle in the served HTML (not just assumed from source order —
read directly off the actual response), the served JS bundle contains
the literal strings `postwarden-sidebar-pinned`, `postwarden-sidebar-
collapsed-`, `Budget Grid`, `Log out`, and `Toggle menu`, and the served
CSS bundle contains `.sidebar-toggle`, `.flash-ok`, `.chevron-down`, and
`.sidebar-pinned`. `GET /entries` and `GET /reports/trial-balance` still
answer `401` (the static mount still doesn't shadow the API), `GET
/favicon.svg` still `200`. The full backend test suite — 523 tests,
untouched by this phase — stays green, confirming no regression from the
`App.tsx` change. **Not verified**: an actual browser rendering and
interacting with the shell (hover-preview, click-to-pin, per-group
collapse, the Escape-key close, the mobile breakpoint) — no browser tool
exists in this session, the same carried-forward gap Phase 2.3 already
tracks in Open questions; this phase adds more surface it applies to
(real pointer/keyboard interaction, not just static rendering) but not a
new kind of gap.

**Next up:** Phase 2.5 (per-widget decisions — Radix/shadcn vs. porting
the existing JS); close the Docker `docker compose up -d --build`
verification gap and the no-browser-tool gap (now covering 2.1 through
2.4) whenever this machine's Docker daemon can reach its registry again
or a browser tool becomes available.

---

**Phase 2.5 done.** The decision, per widget: **port the existing JS as a
React component, not Radix/shadcn** — for all four (combobox, date
picker, confirm dialog, number stepper). Reasoning is exactly what the
checklist entry predicted: each one encodes a real, previously-debugged
browser-quirk fix (the iOS `select()` no-op in `combobox.js`, macOS
Safari's text-fields-only default Tab order in `datepicker.js`'s explicit
`tabIndex={0}`s, the roving-tabindex day grid) that an off-the-shelf
component wouldn't reproduce for free, and re-discovering any of them
from scratch against a new library would just be paying the same
debugging cost twice. `frontend/src/widgets/`:

1. **`NumberStepper.tsx`** — the simplest of the four. A controlled
   component (`value`/`onChange` props, unlike legacy's DOM enhancement
   of a server-rendered field), but the actual step logic still goes
   through the native input's own `.stepUp()`/`.stepDown()` via a ref
   rather than reimplementing step/min/max arithmetic by hand, so the
   browser's own validation semantics stay authoritative — including
   `number-stepper.js`'s own try/catch fallback for when stepUp/stepDown
   throw at a bound.
2. **`ConfirmDialog.tsx`** (+ `confirmContext.ts`) — a `useConfirm()`
   hook returning `(message, opts) => Promise<boolean>`, same shape as
   `confirm.js`'s own `PostWardenConfirm.ask()`, backed by a
   `ConfirmProvider` mounted once at the true app root (`main.tsx`, above
   `Shell`, since a confirm dialog is a cross-cutting concern independent
   of the app chrome). Ports the two-item Tab focus trap, Escape-to-
   cancel, backdrop-click-to-cancel, and returning focus to whatever had
   it beforehand. **Deliberately not ported**: `confirm.js`'s
   `<form data-confirm="...">` auto-wiring — a convention for
   progressively-enhanced server forms with no SPA equivalent, since
   every write already goes through a typed API call a component
   controls directly rather than a bare form submit to intercept. Split
   into two files (`confirmContext.ts` holding the context/hook,
   `ConfirmDialog.tsx` holding only the `ConfirmProvider` component)
   after `oxlint`'s `react(only-export-components)` flagged mixing a hook
   and a component in one file as a Fast Refresh hazard — a real,
   self-caught issue, same category as Phase 2.4's own lint fix.
3. **`DatePicker.tsx`** — the most involved port. Controlled
   (`value`/`onChange` on an ISO string), otherwise a close behavioral
   match to `datepicker.js`: month navigation clamped (not wrapped) at
   month boundaries, the roving-tabindex day grid, full arrow-key/
   PageUp/PageDown/Home/End navigation once a day cell has focus, the
   one-tick-deferred outside-Tab-close (`focusout` + `setTimeout`, ported
   with `datepicker.js`'s own comment explaining why the defer matters —
   arrow-key re-renders briefly leave nothing focused mid-swap, which
   reads as "focus left the widget" if checked synchronously), and every
   explicit `tabIndex={0}` the original sets for the Safari default-Tab-
   order fix. The one structural difference from the original: legacy's
   `render()` rebuilds the day-button DOM and re-queries/focuses it
   inline, synchronously, in the same function; React can't do a same-
   tick DOM query before paint, so `focusDay()` stages the target day in
   a ref and a `useEffect` keyed on `[open, viewDate, rovingIso]` does
   the actual `.focus()` once that render has committed — same visible
   behavior, different mechanism forced by the framework.
4. **`Combobox.tsx`** — controlled over a plain `options: {value,
   label}[]` list instead of enhancing a real `<select>`, since the SPA
   has no server-rendered fallback markup underneath it to preserve
   (legacy's own stated reason for keeping the native `<select>` in the
   DOM doesn't apply once `value`/`onChange` are already the source of
   truth). Ports the filter-as-you-type panel, arrow-key navigation, the
   optional "+ Create "<name>"" row, and — deliberately — the exact
   blur-resolution behavior `combobox.js`'s own comment documents at
   length (commit the best match on Tab/blur same as Enter would; clear
   to blank only if the list actually has an unset option to clear to;
   otherwise revert). `onCreate` is a prop returning
   `Promise<ComboboxOption | null>` rather than a baked-in `fetch` call:
   legacy owned the real `<select>` and could append an `<option>` to it
   directly on a successful create; this component only ever renders
   whatever `options` prop it's given, so the caller's own state (wherever
   `options` comes from) has to gain the new entry too, or it disappears
   again next render even though `value` still points at it — documented
   in the prop's own comment, not left implicit.

`App.tsx` grew a temporary `WidgetPreview` section exercising all four
(a Combobox with a working create flow, a DatePicker, a NumberStepper,
and a button that calls `useConfirm()`) — explicitly marked for deletion
once Phase 3's real archetype screens give each widget an actual caller;
it exists so there's something concrete for the build/lint/bundle-content
verification below to check against, the same reasoning Phase 2.2's
`/healthz` check and Phase 2.4's `PLACEHOLDER_USER` already established.

**Verified for real, the same way as 2.3/2.4.** A real `npm run build`
(`tsc -b && vite build`) — one real type error along the way (a
`ComboRow[]`-vs-`ComboboxOption[]` inference mismatch in `Combobox.tsx`'s
row-building, fixed with an explicit annotation) — and a real `npm run
lint` (`oxlint`) both come back clean, the lint pass only after the
`confirmContext.ts` split described above. A real `uvicorn
postwarden.main:app` against `backend-db-1` (the same already-running
`postgres:16` container the last two phases used) served the rebuilt
bundle end to end: the pre-paint `<script>` still sits ahead of the
injected stylesheet/module bundle in the served HTML, the served JS
bundle contains the literal strings `combobox-input`, `date-panel`,
`number-step`, `confirm-overlay`, `Creating…`, `No matches`, `Couldn't
reach the server`, and the demo's own `Reverse this entry?` confirm
message, and the served CSS bundle contains `.combobox-panel`,
`.date-panel`, `.number-step`, `.confirm-overlay`, and `button.quiet`
(checked minified, `input,select,textarea` with no spaces after the
commas — a byte-diff false alarm caught and re-checked against the
minifier's actual output, not a missing rule). `GET /entries` and `GET
/reports/trial-balance` still `401`, `GET /favicon.svg` still `200`. The
full backend test suite — 523 tests, untouched by this phase — stays
green. **Not verified, same standing gap**: real browser interaction —
typing into the combobox and watching it filter, opening the date picker
and arrowing around the grid, tabbing through the confirm dialog's focus
trap, clicking the number stepper's chevrons — no browser tool exists in
this session; folded into the same Open Questions entry Phase 2.3/2.4
already track, now covering every interactive surface built so far.

**Phase 3.1 done.** Login — the first of Phase 3's four archetype
screens, and per `REBUILD.md` §6 the one meant to "prove the pipeline end
to end." It does: `App.tsx`'s old `GET /healthz` check and hardcoded
`PLACEHOLDER_USER` (both explicitly temporary stand-ins since Phase
2.1/2.4) are gone, replaced by a real three-way branch on session
state — loading, anonymous (`LoginPage`), or authenticated (`Shell`) —
backed by a real cookie session a real `POST /login` created against
the real Postgres container.

Two backend gaps surfaced by actually building the frontend side of
this, both closed here rather than deferred, since neither is separable
from "login works end to end":

1. **`GET /me` now echoes `csrf_token`, not just `id`/`username`.** The
   gap: `POST /login`'s response already carries the new session's CSRF
   token, but a page load riding an *existing* still-valid cookie (the
   common case — most page loads are not themselves a fresh login) had
   no way to learn it at all. Same value `login` already created, not a
   new one; `router.py`'s own docstring and `backend/tests/modules/
   auth/test_router.py`'s `test_me_returns_the_logged_in_user` both
   updated.
2. **A new, unauthenticated `GET /config`** (`main.py`, next to
   `/healthz` — same "no DB touch, nothing worth a router/service split
   for" reasoning) exposes `version`/`demo_banner`/`demo_user`/
   `demo_password`, replacing the Jinja globals `login.html`'s
   auth-brand corner and demo callout, and `base.html`'s footer, used to
   read directly. **A real, deliberate security-relevant departure from
   just mirroring those globals**, spelled out in the route's own
   docstring: Jinja's `{% if demo_banner %}` meant `demo_user`/
   `demo_password` only ever reached an actual HTTP response on a real
   demo instance, even though the globals themselves were always
   populated server-side; a JSON body has no equivalent of a template
   conditionally omitting a value from its own output, so `/config`
   makes that conditional explicit — omitting both fields whenever
   `demo_banner` is false, not just when they're empty. Skipping that
   would leak any deployment's real bootstrap-admin password (which
   `POSTWARDEN_ADMIN_PASSWORD` sets regardless of demo mode) to any
   unauthenticated caller. Four new tests in `backend/tests/test_main.py`
   cover both the omission and the inclusion case, plus the missing-file
   tolerance below.
   - **`version` needed a real file to read**, and `postwarden_static_dir`'s
     own "resolve relative to `__file__`" trick doesn't carry over
     unchanged: a local checkout's repo root sits three directories above
     `config.py` (`backend/src/postwarden/config.py` → repo root), but
     `backend/Dockerfile`'s runtime stage COPYs everything into
     `WORKDIR /srv/postwarden` directly — only *two* directories up from
     the same file once installed there. `postwarden_version_file`
     (`config.py`) tries both candidates in order and tolerates neither
     existing (`main.py`'s `/config` route catches `OSError` and answers
     `""` rather than a 500 — a backend-only checkout, or an image built
     without the new `COPY VERSION .` line, shouldn't break the route
     over a missing footer string). Two new `test_config.py` tests cover
     the real-checkout resolution and the override.

On the frontend, `frontend/src/auth/`:

- **`sessionContext.ts` + `SessionProvider.tsx`** — same two-file split
  `confirmContext.ts`/`ConfirmDialog.tsx` already established for the
  identical `oxlint react(only-export-components)` reason. `useSession()`
  exposes `status` (`'loading' | 'authenticated' | 'anonymous'`), `user`,
  and real `login()`/`logout()` functions backed by `client.POST('/login'
  | '/logout', ...)`. Mounted once at the true root in `main.tsx`,
  alongside (and outside) `ConfirmProvider` — neither reads from the
  other.
- **`LoginPage.tsx`** — the split-screen login itself, ported from
  `login.html`. Two real differences from the template, both dictated by
  the medium rather than a design change: no `ok=`/`err=` query-string
  flash (a local `error` state does the same job, since the same
  component stays mounted through a failed attempt instead of a page
  redirecting back to itself), and the demo callout's prefilled
  credentials/version now come from `GET /config` (`useAppConfig`)
  instead of Jinja globals baked into the initial HTML — seeded into the
  username/password fields exactly once, via a ref guard, not a "seed
  while the field reads empty" check that would have silently refilled
  the field if a user cleared it by hand after config had already
  loaded.
- **`api/client.ts`** now attaches `X-CSRF-Token` to every non-`GET`
  request via `openapi-fetch`'s own `use()` middleware, reading a plain
  module-level variable (`setCsrfToken`) `SessionProvider` is the only
  writer of — exactly the extension point that file's own Phase 2.2
  comment already predicted ("the obvious place to add that once Phase
  3's login screen gives it a token to read"). Also added: an
  `onUnauthorized` callback, fired on any `401` from any request, that
  `SessionProvider` registers to fall back to `'anonymous'` — the
  closest equivalent this SPA has to legacy `auth_gate`'s own redirect-
  to-`/login` on a stale/expired cookie, without a client-side router to
  actually redirect through yet (see below).
- **`api/useAppConfig.ts`** — a plain hook (not a Context; `LoginPage`
  and `Shell`'s footer are the only two callers, and they're mutually
  exclusive in practice) wrapping the new `GET /config`.
- **`shell/Shell.tsx`** gained a `version?: string` prop, closing the one
  gap Phase 2.4's own version of this file's comment left open — the
  footer now reads `PostWarden v{version}` (or just `PostWarden`, the
  same tolerant-degradation choice `/config` itself makes, when
  `version` is empty) instead of a bare, permanently-incomplete
  `PostWarden`.

**A router decision this phase deliberately still defers.** `App.tsx`
branches on `session.status` alone, not a URL — there's still no
client-side router anywhere in the frontend, and Sidebar/Topbar's own
nav links are still plain `<a href>` full-page navigations, exactly as
Phase 2.4 left them. Login doesn't force this decision: "authenticated
or not" has no URL of its own to conflict with. The genuine forcing
function — `GET /entries` already being the Journal's own JSON data
route, so a same-path client route can never work without deciding how
the app-shell HTML and the JSON API stop sharing a path at all
(`main.py`'s own long-standing comment on its static mount) — doesn't
land until a *second* authenticated screen actually needs its own
distinct URL. That's Phase 3.2 (tags), not this phase.

**Verified for real.** Backend: `postwarden_version_file`'s two-candidate
resolution, `/config`'s demo-omission/-inclusion logic, and `/me`'s new
`csrf_token` field each have real `pytest` coverage — 529 passed (523 +
6 new), the 60 pure-Postgres tests untouched. A real `npm run build`
(`tsc -b && vite build`, two casts needed — `data as unknown as
AppConfig`/`LoginBody`, since `/login`/`/me`/`/config` all return a bare
`dict` FastAPI can only describe as `{[key: string]: unknown}` in the
generated OpenAPI schema, same class of gap `client.ts`'s own comment
already flagged) and a real `npm run lint` (`oxlint`) both come back
clean. A real `uvicorn postwarden.main:app` against `backend-db-1`
proved the actual flow end to end over real HTTP, not just through
FastAPI's `TestClient`: `POST /login` with a wrong password →
`401 {"detail": "Invalid username or password"}`; with `POSTWARDEN_
ADMIN_USER=david`/`_PASSWORD=devpassword` → `200` with a real session
cookie and `csrf_token`; `GET /me` with that cookie echoes the identical
`csrf_token`; `POST /logout` clears it (`GET /me` → `401` again); toggling
`POSTWARDEN_DEMO_MODE` between requests flips `/config`'s `demo_user`/
`demo_password` between `null` and the real values with no restart-order
bug once the earlier `lru_cache`d-settings/stale-process mixup during
this same check was caught and re-run correctly. The served bundle
contains `auth-split`, `auth-wordmark`, `demo-callout`, `X-CSRF-Token`,
and `csrf_token` in the JS, and `.auth-split`/`.auth-wordmark`/
`.demo-callout`/`.checkline`/`.grid-form`/`label.field` in the CSS. `GET
/entries`, `/reports/trial-balance`, `/staging`, `/accounts` are still
`401` with no session — the static mount still doesn't shadow any
module's own routes. **Not verified, same standing gap, now covering the
login screen's own interactive surface too**: real browser interaction
— autofocus landing in the username field, tabbing through the form,
the demo callout's responsive reflow to `order: -1` at the 720px
breakpoint, submitting via Enter instead of clicking — no browser tool
exists in this session.

**Phase 3.2 done.** Tags — the Management/CRUD archetype, and the screen
that finally forced the client-router-vs-API-path decision Phase 3.1
deliberately left open.

**The router decision, resolved.** The obvious-looking fix — prefix
every data route with `/api` — turned out to be wrong the moment it was
actually checked against the routes that exist, not just assumed:
`analytics/router.py` (Phase 1.13) already owns literal `/api/accounts`,
`/api/entries`, `/api/trial-balance`, etc. as a real, external, already-
shipped contract (the Connect BI feature's `.pbids` files point Power BI
at those exact URLs today). Prefixing `modules/entries/`'s own `/entries`
the same way would land it at `/api/entries` too — colliding with
analytics' route of the same name, a genuinely different thing (a flat
BI-consumer mirror vs. the Journal's own filter/paginate endpoint), not
a cosmetic clash. Renaming analytics' own paths instead was rejected for
the same reason: a real, already-saved `.pbids` file isn't internal
plumbing free to move. **Resolution: the SPA's own client-side routes
live under `/app/*` instead** — a namespace no backend router has ever
used (grep-checked, not assumed), so zero routers changed. `main.py`
gained two new routes, `GET /app` and `GET /app/{path:path}`, registered
ahead of the static mount and only when `postwarden_static_dir` exists —
both just serve `index.html` so a direct browser navigation or refresh
at, say, `/app/tags` actually loads the SPA instead of 404ing (`Static
Files(html=True)` only resolves `index.html` for a literal directory,
not an arbitrary client-route path). The actual response-building logic
is a small module-level `_spa_index_response()`, split out specifically
so it's unit-testable with no dependency on whether a real frontend
build exists in whatever environment runs the test — same "only if it
exists" gap the plain static mount has always had, closed here instead
of carried forward. `GET /tags` itself is completely untouched: still
the bare path, still 401-gated, still JSON, never HTML.

On the frontend, `main.tsx` now wraps the whole tree in a react-router-dom
`BrowserRouter` (real History-API routing, not hash-based — the new
`/app/*` fallback routes are what make that actually work for a direct
navigation, so there was no reason to sidestep the problem with a hash
router instead of solving it). `App.tsx` renders a real `<Routes>` once
authenticated: `/` is the existing Dashboard placeholder, `/app/tags` is
the new `TagsPage`. `Sidebar.tsx`/`Topbar.tsx`'s Dashboard/wordmark links
became real `<Link>`s; `nav.ts` gained a `client?: boolean` flag so
`Sidebar.tsx` can render a `<Link>` for a link with a real screen behind
it and a plain `<a href>` for everything else — every other sidebar link
is untouched, still a full-page navigation into what's still a raw JSON
response today, same pre-existing rough edge every unbuilt screen
already had, not worsened, not yet fixed. Each becomes real on its own
Phase 4 turn.

**`frontend/src/tags/TagsPage.tsx`** — ported from `app/templates/
tags.html` + `app/static/entity-manage.js`. Same Select/Merge/+Add/table/
Status/Archive shape as legacy: a collapsible `+ Add tag` panel, a table
with per-row inline rename (click Edit, Enter to save, Escape to
revert), Archive/Unarchive, and Delete (behind `useConfirm()`, exact
legacy message and `danger: true`), plus a Select-mode toolbar with a
tri-state "select all" and a Merge dialog. Two genuinely reusable pieces
were factored out, not the whole page — deliberately narrower than
"build one generic Management/CRUD component now," since legacy's own
five entities differ enough (Scenarios' Lock vs. Archive, Account
Levels has no Merge at all) that forcing one abstraction ahead of a
second real case (Payees, Phase 4.2) risks fighting those differences,
the same "one module, five sections, only the truly-identical parts
factored out" call Phase 1.9 already made on the backend for this exact
group of entities:

1. **`widgets/useSelectMode.ts`** — the select-mode/checked-set/
   indeterminate-select-all mechanics, generic over any numeric id list.
   Takes its `selectAllRef` as a parameter rather than creating and
   returning one — not a style preference: the plainer shape (`useThing()`
   returns `{ ref, ...state }`, caller does `ref={thing.ref}`) is a
   confirmed real `oxlint` `react(refs)` false positive, reproduced with
   the smallest possible repro (a two-line custom hook), that flags every
   *other* property read off the same returned object too, not just the
   ref itself. Passing the ref in instead of out is what actually made
   `npm run lint` clean rather than papering over three warnings.
2. **`widgets/MergeDialog.tsx`** — the merge popup, reusing
   `ConfirmDialog.tsx`'s own `.confirm-overlay`/`.confirm-modal`/
   `.confirm-actions` CSS (already generic per that file's own Phase 2.5
   comment) but not built on `useConfirm()` itself, since a merge has to
   hand back a typed survivor name, not just a boolean. Deliberately has
   no Tab focus trap, unlike `ConfirmDialog.tsx`'s own cancel/OK loop — a
   real, pre-existing gap in legacy's own `entity-manage.js` (wires
   Escape but never Tab, unlike `confirm.js`'s dialog), ported as-is per
   `REBUILD.md` decision 4, not fixed while passing through.

Smaller decisions:

- **A stale legacy CSS comment, found and not trusted over the actual
  template.** `style.css`'s own "entity manager" comment claims "Tags:
  Edit/Delete only... see main.py's Tags section for why it carries no
  Archive" — but `tags.html` itself unambiguously renders an Archive/
  Unarchive toggle-active form, and `modules/reference/router.py`'s own
  `POST /tags/{id}/toggle-active` route exists and works. Read as
  documentation drift in legacy itself (the comment predates Tags
  gaining Archive and was never updated), not a real asymmetry — ported
  the CSS comment verbatim anyway (byte-exact porting doesn't rewrite
  legacy's own prose, even prose this port's own research shows is
  wrong), but `TagsPage.tsx` renders the real, working Archive/Unarchive
  button regardless, matching the template and the route, not the
  comment.
- **The Merge button is always in the DOM, not `select-only`.** Checked
  directly against `tags.html`'s own markup: unlike the "select all"
  checkbox (which does carry `select-only`), Merge only ever gets
  `disabled` toggled, never hidden outside Select mode. A real, if
  slightly odd, legacy behavior — ported exactly, not "fixed" to match
  the more consistent-looking pattern.
- **Every mutation reloads the full tag list from `GET /tags`** rather
  than patching local state from each write route's own narrower
  response — small dataset, and it's what actually matches legacy's own
  redirect-and-re-render-from-the-server behavior most faithfully, not
  an approximation of it.
- **The merge survivor is derived by filtering the page's own sorted
  tag list against the checked-id `Set`, not insertion/click order** —
  same "DOM order, not click order" rule `entity-manage.js`'s own
  `Array.from(table.querySelectorAll(...))` read gave for free, which a
  plain `Set` can't answer on its own without this extra step.
- **The Entries count column is plain text, not legacy's `amount-link`
  through to a filtered Journal.** `/app/entries` doesn't exist yet
  (Phase 3.4) — same "don't reach into a screen that doesn't exist yet"
  reasoning every prior backend phase already applied to `modules/
  reference/`.
- **`index.css` gained ten more byte-verified ranges** (table.ledger's
  base/th/td/.num — not the ~260-line report-table/sticky/t-account
  variants, those wait for Phase 3.3/4.6 — `.dim`, `.mono`, `.bar`,
  `.select-only`, checkbox/radio custom styling, the whole "entries
  browser" `details.entry`/`.entry-new` block, and the entity-manager
  block). The `details.entry` range was imported whole rather than
  surgically trimmed to only what Tags' own "+ Add tag" panel needs —
  `entry-journal`/`entry-staging`'s grid columns and the per-row
  checkbox gutter aren't used here, but belong to the same source
  comment block and exist to be reused unchanged once Journal/Staging
  need them, so pre-importing avoids re-opening this file later to add
  back what would've been surgically excluded the first time.
- **`react-router-dom@^7` added via `npm install --legacy-peer-deps`** —
  not new friction this phase introduced: `openapi-typescript@7.13.0`'s
  own peer range (`typescript@^5.x`) already conflicts with this
  project's actual `typescript@~6.0.2`, and any *new* dependency install
  now re-surfaces that pre-existing mismatch as a hard `ERESOLVE` error
  (the original lockfile predates npm re-checking it strictly). Noted
  here since it'll bite the next `npm install` too, not just this one.

**Verified for real.** Backend: `_spa_index_response()`'s missing-file/
present-file branches both have real `pytest` coverage via `tmp_path` +
`monkeypatch`, plus a real `TestClient` hit against the actual built
`/app/tags` route (this environment has a real `npm run build` output
on disk, so that path was exercised for real, not just the extracted
helper) — 532 passed (529 + 3 new), the 60 pure-Postgres tests untouched.
A real `npm run build` and a real `npm run lint` both came back clean —
getting there surfaced one genuine `oxlint` false positive (`react(refs)`
on a custom hook returning `{ ref, ...state }`, confirmed with a minimal
repro before working around it, not just suppressed) and one real
`react(set-state-in-effect)` catch (a bare `useEffect(() => reload())`
where `reload` was a named async function — restructured to inline the
initial fetch, matching `useAppConfig.ts`'s own already-clean shape,
rather than silencing the warning). A real `uvicorn postwarden.main:app`
against `backend-db-1` proved the full flow over real HTTP: login, then
`GET /app/tags` → `200` serving the real SPA shell (confirmed `id="root"`
in the body) while the bare `GET /tags` still `401`s with no session;
create (`"Groceries"` → stored as `"groceries"`, confirming `parse_tags`'
lowercasing reaches the API as expected), rename, toggle-active, merge
(two tags → one survivor, `entries_affected` correct), delete, a bad id
→ `400` (not a 404 or a 500), and a write with no `X-CSRF-Token` header
→ `400`, all against the real `tags` table. The served bundle's JS
contains `entity-table`/`Add tag`/`Merge into`/`Deselect`; the served CSS
contains `.entity-table`/`.select-only`/`.inactive`. **Not verified, same
standing gap, now covering Tags' own interactive surface too**: real
browser interaction — the inline-edit focus/select/Escape behavior, the
Select-mode checkbox reveal, the Merge dialog's own focus/Escape
handling, tri-state "select all" — no browser tool exists in this
session.

**Phase 3.3 done.** Trial Balance — the Point-in-time report archetype,
and the first screen this rebuild renders a real account tree or a real
money figure on.

**`frontend/src/reports/TrialBalancePage.tsx`** — ported from
`app/templates/trial_balance.html` + `report-tree.js`. Same shape as
legacy: a Scenario/As-of filter bar, prev/next-month links, two
checkboxes (zero balances, true/raw balances), Export CSV/XLSX, and a
collapsible account tree ending in a grand total row that reads "In
balance"/"Out of balance." Two reusable pieces factored out, matching
Phase 3.2's own "only the genuinely identical parts" scope:

1. **`format/money.ts`** — `formatMoney`/`isZeroAmount`, ported from
   `money-format.js`'s own `format()`/`prefs()` (same `localStorage` key
   and defaults, `postwarden-number-format`). Deliberately *not* a port
   of that file's own DOM-rewrite mechanism (a `<span class="money-fmt"
   data-value="...">` written once by Jinja, then rewritten client-side
   after the fact) — that existed only because Jinja renders static HTML
   once per page load; React re-renders from state, so there's no static
   HTML to rewrite and no no-JS fallback case to cover. Every screen just
   calls `formatMoney(value)` and renders the string — same "port the
   behavior, not a legacy workaround for a rendering model this app no
   longer has" call `modules/auth/router.py`'s `GET /me` (Phase 1.11)
   already made for an analogous reason. No Settings screen writes this
   `localStorage` key yet (out of scope, same as every prior phase's
   "don't reach into a screen that doesn't exist yet"), so every amount
   renders with legacy's own defaults until one does.
2. **`widgets/useCollapsibleTree.ts`** — the collapse/expand mechanics
   from `report-tree.js`, generic over any `{id, parent_id, has_children}`
   row list and persisted to `localStorage` under the same
   `data-collapse-key` value legacy used
   (`postwarden-trial-balance-collapsed`) — scenario/date-independent,
   so paging through months doesn't reset what a viewer already
   collapsed. Reusable unchanged by Balance Sheet/Variance (Phase 4) and,
   once it exists, Accounts' own level browser (Phase 4.6).
3. **`api/useScenarios.ts`** — a plain `GET /scenarios` hook, same shape
   `useAppConfig.ts` already established (Phase 3.1) for a one-shot,
   no-writer fetch. First real caller of `modules/reference/`'s own
   `GET /scenarios` (Phase 1.9) from the frontend; every future
   scenario-picker screen reuses this unchanged.

Smaller decisions:

- **Filter state lives in the URL's own query string
  (`useSearchParams`), not component state.** The direct equivalent of
  legacy's `<form method="get" data-auto-refresh>` GET-and-redisplay
  design — the page stays bookmarkable/shareable/back-button-able, and
  the prev/next "as of" links can be real `<Link>`s (a genuine history
  push) instead of onClick handlers, matching legacy's own plain
  `<a href>`s rather than approximating them with JS. Filter *edits*
  (scenario/as-of/checkboxes) use `{ replace: true }` instead, though —
  a deliberate difference, not a blind default: `DatePicker.tsx`'s own
  text field (Phase 2.5) fires `onChange` per keystroke, unlike a native
  `<input type="date">`'s single `change` on commit, and pushing a new
  history entry per keystroke while typing a date would spam "back" far
  worse than legacy's own single-submit-per-edit GET ever did.
- **No help-icon.** `trial_balance.html`'s own `.page-head` carries an
  `<a href="/help#reports" class="help-icon">` alongside `.page-sub`;
  `/help` doesn't exist anywhere in this SPA yet (Phase 5, the long
  tail — the whole legacy Jinja app stopped being served the moment this
  branch's `main.py` took over static serving, so linking there 404s for
  real, not just "unbuilt"). `.page-head`/`.page-sub` still render (the
  sub-note is real content), the anchor doesn't. Tags' own `tags.html`
  carries the identical `.help-icon` and Phase 3.2's `TagsPage.tsx`
  already silently omitted it too, undocumented at the time — this
  writes down the reason retroactively rather than reopening that
  commit.
- **No drill-through from a balance to a filtered Journal.**
  `trial_balance.html`'s own `entry_link()` macro turns every non-zero
  leaf balance into an `a.amount-link` pointing at `/entries?account=...`;
  `/app/entries` doesn't exist yet (Phase 3.4), same "don't reach into a
  screen that doesn't exist yet" reasoning Tags' own entry-count column
  already applied to a narrower case (Phase 3.2) — extended here to
  something genuinely more central, since it touches every money figure
  on the page, not one column. `a.amount-link`'s own CSS still shipped
  this phase, ready for Phase 3.4 to wrap the cell in a real `<Link>`.
- **A real type gap found via the actual HTTP response, not assumed:**
  a leaf row's `debit_balance`/`credit_balance` is `string | number`, not
  always `string`. `domain.accounts.build_account_tree`'s own
  `max(total, 0)`/`max(-total, 0)` returns the *literal* Python `int 0`
  (not a `Decimal`) whenever that bare `0` wins the comparison, and
  `json.py`'s Decimal-to-string encoder only runs on an actual `Decimal`
  instance — confirmed live: `"credit_balance": 0` (a bare JSON number)
  came back over real HTTP for exactly this case. `formatMoney`/
  `isZeroAmount` already branch on `typeof value` for the identical
  reason `money-format.js` itself always did; this was a type-annotation
  fix once seen, not a behavior change.
- **`index.css` gained nine more byte-verified ranges** (`.page-head`/
  `.page-sub`/`.help-icon`, `.table-scroll` + `.report-table`'s sizing
  rules, `.report-frame`/`.report-export`, the sticky header/column
  block, the tinted money-column/type-head/subtotal/grand-total rules,
  `.quiet-link`/`a.amount-link`, `.acct-name`/`.depth-N`, and
  `report-tree.js`'s own tree-toggle collapse mechanics — plus one more
  single-line utility, `.small`) — all still deliberately *not* including
  `.period-label`/`.period-agg` (Income Statement Split, Phase 4) or
  `.t-account`/`.two-col`/`.side-nav` (Ledger's card grid, Accounts'
  level browser — Phase 4.6), per Phase 3.2's own note on both. The
  `data-postable="0"` half of the tree-toggle rules (Accounts-only) came
  along anyway, sharing one indivisible comment block in the source with
  `data-has-children="1"` (this page's own selector) — same "whole
  coherent block, not surgically trimmed" call Phase 3.2 already made.

**Verified for real.** 532 backend tests still passing, unchanged (no
backend code needed for this phase — `modules/reports/router.py`'s
`GET /reports/trial-balance` has existed since Phase 1.4/1.14), the 60
pure-Postgres tests unaffected. A real `npm run build` and a real
`npm run lint` both came back clean on the first try — no `oxlint`
findings this phase, unlike 3.1 and 3.2. A real `uvicorn
postwarden.main:app` against `backend-db-1` (seeded via `seed_demo.sql`)
proved the full flow over real HTTP: login, `GET /app/trial-balance` →
`200` serving the SPA shell while the bare `GET /reports/trial-balance`
still `401`s with no session; the real report for `ACTUAL` (Assets/
Liabilities/Equity/Income/Expense sections, a balanced grand total);
`zeros=1&raw=1` toggled together; a nonexistent scenario code returning
`200` with an empty report rather than an error (no scenario-existence
check exists at any layer, matching `fn_trial_balance`'s own behavior —
not "fixed," per `REBUILD.md` decision 4); both CSV and XLSX export
routes responding `200` with the right content type. The served bundle's
CSS contains `report-table`/`tree-toggle`/`acct-name`/`money-first`/
`quiet-link`; its JS contains "Trial Balance"/"Export CSV"/"show zero
balances"/"show true balances." **Not verified, same standing gap, now
covering Trial Balance's own interactive surface too**: real browser
interaction — the tree collapse/expand click target and its persisted
state, the DatePicker popup on this page specifically, hover states on
`.quiet-link`/sticky columns — no browser tool exists in this session.

**Phase 3.4 done — the go/no-go gate, and it passes.** The Journal:
`entries.html` (346 lines) plus ~1,240 lines of hand-written DOM
scripting across `app.js`, `entries-select.js`, `tags-bulk-edit.js`,
`description-edit.js`, `memo-edit.js`, and `entry_templates.js`. No
backend changes needed — `modules/entries/` has existed since Phase 1.5/
1.14, and `modules/reference/`'s `GET /accounts`/`GET /account-levels`/
`GET /payees`/`GET /tags` and `modules/scheduling/`'s `GET /templates`
already carried everything the New entry form needs.

`frontend/src/journal/JournalPage.tsx` is the main deliverable — filter
bar, Select mode + Reverse + Edit tags, the entries list itself, export
links, pager — built on five pieces it composes rather than inlines:

- **`NewEntryPanel.tsx` + `EntryGrid.tsx`/`gridLines.ts`** — the "+ New
  entry" form and its line grid. `gridLines.ts` holds the pure
  `GridLine`/`makeBlankLine`/`isLineUsed`/`ensureTrailingBlank`
  functions (split out once `EntryGrid.tsx` tripped oxlint's
  `react(only-export-components)`, same fix `confirmContext.ts` already
  used for `ConfirmDialog.tsx` in Phase 2.5) so a controlled `GridLine[]`
  array can be trimmed/grown the same way `app.js`'s own DOM-mutating
  version did. Keyboard nav (Enter/Shift+Enter move vertically, same
  column) is a real `querySelector` over the rendered table rather than a
  ref registry — the same blend of React state and direct `.focus()`
  calls `DatePicker.tsx` already uses for its own roving-tabindex grid,
  chosen because that really is how `app.js`'s own `columns()` worked
  (re-querying the DOM on every keypress), and because a query is simpler
  than threading a per-cell ref map through a table that grows and
  shrinks rows on every keystroke. Distribute/Add line/Post/Clear and the
  Alt+N/D/E/S/C shortcuts are all ported; Distribute's own first-row
  special case (see `app.js`'s file comment) and the "never trim the row
  someone's still focused in" guard both carried over unchanged.
- **`TagInput.tsx`** — the chip tag picker, ported from `tags.js`. A
  controlled component (comma-separated `value`/`onChange`, matching
  every server-side consumer's own shape) rather than a hidden-input DOM
  enhancement, reused by the New entry form's own Tags field, the filter
  bar's Tags field (`creatable={false}`, same as legacy's
  `data-creatable="0"`), and `BulkTagsDialog.tsx`.
- **`useInlineEdit.ts`** — the debounce-autosave-with-corrective-cancel
  mechanics behind both `DescriptionCell.tsx` and `MemoCell.tsx`,
  factored out of what were two deliberately-separate legacy files
  (`description-edit.js`/`memo-edit.js`) into one hook. Legacy kept them
  apart on the grounds that "two files this close in shape is exactly the
  amount of duplication worth keeping simple... a third such widget would
  be the point to actually factor one out" — but that was a judgment
  about the cost of *sharing* in hand-wired DOM code specifically; in
  React, a bug fixed once in the hook benefits both cells for free, at no
  coordination cost, so sharing it is the better default here, not a
  departure from that reasoning. The one real behavioral knob between the
  two (a memo can autosave blank; a description can't) is the hook's
  `allowBlank` flag — the other legacy difference (stopping `<summary>`'s
  native toggle on click) stayed a DOM concern the caller handles, not
  the hook's. The iPad bug this whole pattern exists to survive
  (BACKLOG.md — a hardware-keyboard setup where blur/Enter's own save
  never landed) is preserved exactly: a draft autosaves on a 600ms
  debounce while still typing, and `cancel()` re-POSTs the pre-edit value
  if a debounced draft already reached the server.
- **`BulkTagsDialog.tsx`** — the Journal's "Edit tags" popup, ported from
  `tags-bulk-edit.js`. Reuses `ConfirmDialog.tsx`'s own `.confirm-
  overlay`/`.confirm-modal` CSS (an `<h3>` plus `TagInput.tsx` instead of
  a message and Cancel/OK) rather than `useConfirm()` itself, same
  reasoning `MergeDialog.tsx` already gives: this needs to run a live
  side effect per chip add/remove (one `POST /entries/tags` each,
  diffed against the union of tags across whatever's checked), not just
  resolve a boolean once.

**Smaller decisions:**

- **`useSelectMode.ts` made generic (`<T>`), not forked a second time.**
  Every prior caller (Tags; Payees in Phase 4.2) has a plain integer id;
  the Journal's own entries are keyed by a random 6-character string
  (`SPEC.md` decision 17). Widening the hook to `useSelectMode<T>` costs
  nothing at either existing call site (both still infer `T = number`)
  and keeps one implementation instead of two copies that could drift.
- **The filter bar's own state lives in the URL** (`useSearchParams`),
  same design `TrialBalancePage.tsx` already established — but the
  push-vs-replace call inverts here, and deliberately so: every control
  in `entries.html`'s own filter form really did cause a full page
  navigation in legacy (`auto-refresh.js`'s `form.requestSubmit()`), so a
  browser-history entry per filter change is exactly the right parity, not
  something to avoid the way it was for Trial Balance's per-keystroke `As
  of` field. Free-typed fields (Search, the Amount value/value2 pair) stay
  local, uncommitted state until a real form submit — Enter in any field,
  or the Search icon's click — matching `auto-refresh.js`'s own
  deliberate carve-out for exactly those two fields.
- **No "Back to report" link.** Legacy's own `back=` only ever arrives via
  a drill-through from another report page; nothing in this rebuild
  produces one yet (Trial Balance's own Phase 3.3 write-up chose plain
  text over a real link for the identical reason). Reintroduce once a
  report actually links here with `back=` set, rather than half-wiring a
  parameter nothing sends.
- **No help-icon**, same omission every `.page-head` since Phase 3.2 has
  made — `/help` doesn't exist in this SPA yet (Phase 5).
- **The reversal/tag badges are real click targets** (`applyFilters` to
  jump to the reversed/reversing entry, or to filter by that tag) — these
  *do* have a live target today, unlike Trial Balance's own deferred
  drill-through-to-Journal links, since they only ever navigate within
  this same page.
- **`postable_accounts_for_pickers`/`postable_accounts_by_scenario`
  ported client-side**, not as new backend endpoints — `widgets/
  usePostableAccounts.ts` recomputes both from `GET /accounts` + `GET
  /account-levels` + the caller's own `GET /scenarios`, matching
  `fn_line_account_guard` exactly (a leaf account, or anything sitting at
  a scenario's own `base_level_id`'s depth). Consistent with REBUILD.md
  decision 3's line: the frontend fetches reference data separately, but
  nothing stops it from re-deriving a pure filter over that data the way
  the pure `domain/` layer would on the backend.
- **A real, confirmed HTTP-round-trip discovery, not a gotcha this time**:
  `journal_lines.debit`/`.credit` are `NOT NULL GENERATED ALWAYS AS (...)`
  columns (`db/schema.sql`), so — unlike Trial Balance's `max(int, 0)`
  gap — every leg's debit/credit always serializes as a real Decimal
  string ("0.00", never a bare `0`). `JournalPage.tsx` reuses `format/
  money.ts`'s `isZeroAmount`/`formatMoney` regardless, for the same
  blanking-a-zero-cell behavior every other report already has, not
  because this route needed the `string | number` widening.

**Verified for real.** 532 backend tests still passing, unchanged (no
backend code touched this phase). The 60 pure-Postgres tests green. A
real `npm run build` and `npm run lint` both clean. A real `uvicorn
postwarden.main:app` against `backend-db-1` (seeded via `seed_demo.sql`)
proved the full flow over real HTTP, not just a clean compile: login;
`GET /app/entries` → `200` serving the SPA shell while bare
`GET /entries` stays `401` unauthenticated; `GET /entries`/`/accounts`/
`/account-levels`/`/payees`/`/tags`/`/templates`/`/scenarios` all `200`
with the exact response shapes the TypeScript interfaces assume; a real
`POST /entries` posting a balanced two-line entry; `GET /entries?entry_
id=...` finding it back; `POST /entries/{id}/edit-description`, `POST
/entries/lines/{id}/edit-memo`, and `POST /entries/tags` all landing;
`POST /entries/{id}/reverse` posting a real reversal; `POST /entries/
reverse` (bulk) against an already-reversed entry returning `200` with
the failure captured in its own `errors` array rather than aborting the
whole batch (`service.reverse_entries_bulk`'s own per-entry `SAVEPOINT`,
confirmed live, not just read); both `/entries/export.csv` and `.xlsx`
`200`ing with the right content-type and the edited description/memo
actually showing up in the export. The served bundle's JS contains "New
entry (Alt"/"Distribute (Alt"; its CSS contains `tag-chip-remove`.
**Not verified, same standing gap, now covering the Journal's own
(considerably larger) interactive surface too**: real browser
interaction — the full keyboard flow through the entry grid, Tab
order, Distribute/Add line/Clear's focus management, the tag chip
picker's arrow-key nav, `<details>` expand/collapse per entry, and
every Alt+ shortcut — no browser tool exists in this session. Close this
gap, and the Docker `docker compose up -d --build` verification gap
(now covering all of Phase 2 and Phase 3.1–3.4), whenever a browser tool
or this machine's Docker registry access becomes available.

**Next up:** Phase 4 — fill in the remaining 22 screens by archetype,
largely configuration now that all four archetype components exist.
`REBUILD_STATUS.md`'s own Phase 4 checklist starts with 4.1 (remaining
Range/period + Point-in-time reports), which reuses `useCollapsibleTree.ts`/
`useScenarios.ts` from Trial Balance, and 4.2 (remaining Management/CRUD),
which reuses `useSelectMode.ts`/`MergeDialog.tsx` from Tags.

**Phase 4.1, screen 1 of 5 — Balance Sheet done.**
`frontend/src/reports/BalanceSheetPage.tsx`, modeled directly on
`TrialBalancePage.tsx`'s own pattern (URL-state filters via
`useSearchParams`, one `useEffect` fetch, `useCollapsibleTree` with its
own `localStorage` key). No backend changes — `GET /reports/balance-sheet`
has existed since Phase 1.4/1.14. One real structural difference from
Trial Balance, confirmed by reading `service.balance_sheet` directly
rather than assumed: the response is **not** the `{grouped: [...]}`
per-type-section shape — it flattens straight to three separate top-level
arrays (`assets`/`liabilities`/`equity`), each already a `flatten_tree()`
row list with no section wrapper, plus a separate `earnings_lines` list
of plain 2-tuples (`[label, amount]`), not `{label, amount}` objects.
Liabilities/Equity rows negate their stored (credit-normal) `subtotal`
for display — a `sign: 1 | -1` prop on a shared `SectionRows` sub-component
rather than repeating the ternary `balance_sheet.html`'s own three copies
use.

Wired into `App.tsx` (`/app/balance-sheet` route, `routeKey`,
`PAGE_TITLES`) and `nav.ts` (`balance_sheet` link flipped to
`client: true`, href repointed from `/balance-sheet` to
`/app/balance-sheet`) — the first of Phase 4.1's five links to make that
flip.

**Verified for real**, including — for the first time this rebuild — an
actual browser pass, not just source-level reasoning: this session had
live `mcp__Claude_Browser__*` tools, closing the gap every phase since
2.3 had to carry forward as an open question. `docker compose up -d
--build` from `backend/` built clean (Docker registry access also
worked fine this session — the sandbox-specific pull restriction noted
in the Open questions section below does not apply here); `tsc -b` +
`vite build` clean (via the Dockerfile's own frontend-build stage);
`oxlint` clean (0 warnings, via a throwaway `node:22-slim` container
since this machine has no local `node`/`npm` on `PATH`); backend `pytest`
(532 passed, unchanged — no backend code touched) and the 60
pure-Postgres tests (`tests/test_invariants.py`/`test_cashflow.py`, both
run against the same `docker compose`-started Postgres) all green. Then,
in a real browser: logged in, opened the sidebar, clicked through to
Balance Sheet; collapsed/expanded the Assets branch and confirmed
subtotals recompute; toggled "show true balances" and confirmed the
`· simulated monthly close` sub-header note disappears and the two
Current/Prior Year earnings lines collapse into legacy's single "Current
earnings (unclosed)" line, same total either way; clicked the next-month
link and confirmed `as_of` advances while `raw=1` carries forward in the
URL and both Export links; opened the Scenario Combobox and confirmed it
lists the real `ACTUAL`/`BUD2026`/`STAGING` scenarios; confirmed the
grand total row reads "in balance" with Assets (122,544.51) exactly
matching Liabilities + Equity; both `.csv`/`.xlsx` export URLs `200` with
the right content-type over a real authenticated `curl` round trip.

**Phase 4.1, screen 2 of 5 — Cash Flow done.**
`frontend/src/reports/CashFlowPage.tsx` — the first Range/period screen
(Income Statement/Cash Flow, per `UI_CONSISTENCY_AUDIT.md` §1), so the
first to use URL-state `date_from`/`date_to` instead of a single `as_of`,
and the first with no account hierarchy at all (flat sections, no
`useCollapsibleTree`). No backend changes — `GET /reports/cash-flow` has
existed since Phase 1.4/1.14.

**New shared widget: `frontend/src/widgets/PeriodPresetPicker.tsx`** (+
`periodPresets.ts` for the pure logic — split out once oxlint's
`react(only-export-components)` flagged the combined file, same fix
`journal/gridLines.ts`/`widgets/confirmContext.ts` already applied),
ported from `app/static/js/period-picker.js`. Per
`UI_CONSISTENCY_AUDIT.md` §4b's own recommendation to promote Income
Statement's period-preset dropdown to both range reports, this lands
with Cash Flow (its first caller) rather than waiting for Income
Statement. A plain controlled component, not a port of legacy's own
DOM-querying/on-load-reverse-match mechanism — React re-renders the
right selection from whatever's already in the URL, so `matchPreset`
just runs at render time instead of once on load. Every new picker this
phase (this one included) is a `Combobox` from the start, never a raw
`<select>` — the exact bug class the 2026-08-30 QA pass already found
and fixed eight times over.

Structural notes from reading `service.cash_flow_rows`/
`cash_flow_tie_out` directly: `inflows`/`outflows`/`ledger_adjustments`
are flat row lists (`account_code`, `account_name`, `parent_path`,
`amount`, `flagged`, `netted_from: [{account_code, account_name,
amount}]`), and `tie_out` is a nested object
(`ok`/`statement_total`/`cash_leg_net`/`balance_delta`/`beginning`/
`ending`). Ported `cash_flow.html`'s two independent `.flash-warn`
banners (tie-out failure, shown only if `!tie_out.ok`; flagged
multi-cash-leg transactions, shown only if non-empty) and its
Beginning→Inflows→Outflows→optional-Ledger-adjustments→Net-change→Ending
row order exactly, including the `netted_from` sub-line and the
`·multi-cash` flag annotation.

Legacy's `dateformat` filter (used on `flagged_entries[].entry_date`) has
no port yet — same gap `format/money.ts`'s own comment already documents
for a Settings screen that doesn't exist (Phase 4.2/4.7); rendered as
plain ISO text instead, matching `JournalPage.tsx`'s own precedent for
`entry_date` (Phase 3.4), not a new gap this screen introduces.
`entry_link`'s drill-through to a filtered Journal also stays unwrapped,
same "don't reach into a screen that doesn't exist yet"-shaped deferral
Trial Balance's and Balance Sheet's own comments already carry forward
even though `/app/entries` exists today — consistency with those two
beats this screen alone jumping ahead.

Wired into `App.tsx`/`nav.ts` (`cash_flow` → `/app/cash-flow`).

**Verified for real**, same four checks as Balance Sheet: `docker compose
up -d --build` clean; `tsc -b` + `vite build` + `oxlint` clean (`oxlint`
via a throwaway `node:22-slim` container, same as Balance Sheet — this
phase's own lint warning above was caught and fixed this way, not by the
Docker build, which doesn't run lint); 532 backend tests + the 60
pure-Postgres tests green (unchanged, no backend code touched); and a
real browser pass — the flagged-entries banner rendering with its real
transaction (a multi-cash-leg Opening Balance entry from
`seed_demo.sql`), `netted_from` rendering under Salary Income, the
Period Combobox correctly reverse-matching "This month" against the
default `date_from`/`date_to` on load, selecting "Last quarter"
recomputing the range to `2026-04-01`–`2026-06-30` and both sections
correctly showing "No inflows/outflows in this range" with the banners
disappearing, and both `.csv`/`.xlsx` exports `200`ing over a real
authenticated `curl` round trip. No tie-out failure was reproducible
against `seed_demo.sql`'s own data (it ties out clean), so that specific
banner's real rendering is still unverified in-browser — noted rather
than silently skipped.

**Phase 4.1, screen 3 of 5 — Income Statement done**, the hardest data
shape of the five. `frontend/src/reports/IncomeStatementPage.tsx` — rows
mode (a single range, structurally close to every other report) and
Split mode (a period-column-group matrix), discriminated by presence of
`periods_totals` in the response (confirmed by reading
`service.income_statement_rows`/`income_statement_matrix` directly, not
assumed — the two branches return genuinely different shapes, not just
optional fields). No backend changes needed for the screen itself —
`GET /reports/income-statement` has existed since Phase 1.4/1.14 — though
a real, previously-undiscovered backend bug surfaced and got fixed in
this same commit (see below).

**The key simplification**, spelled out in `income_statement.html`'s own
comment on its split branch and leaned on directly: a row/group's
`periods` array (matrix mode only) is "the very same shape a single-
period row/group has." So rather than writing two parallel body-
rendering branches, this component treats rows mode as a one-period
matrix — `periodsOf`/`periodsTotalsOf`/`rowPeriod`/`groupPeriod` paper
over the distinction so `GroupBlock`/`ExpenseGroupBlock`/the "Total
income"/"Net income" rows are each written once and rendered identically
in both modes. The two render paths genuinely differ only in header
shape (a single plain header row vs. Split's two-row period-group
header with `.table-scroll`) — mirroring how close the Jinja source's
own two branches already are.

New shared widgets: none — `PeriodPresetPicker` (Cash Flow) covers this
screen's own Period field too, and every dropdown (Scenario, Compare to,
Split) is a `Combobox`, never a raw `<select>`, same standing rule every
screen since the 2026-08-30 QA fix follows. New CSS ported (confirmed
missing by grep, same "byte-verified range" practice every visual phase
uses): `.period-label`/`.period-start`/`.period-agg`/`.period-agg-average`
(Split view's own column-group styling, `app/static/style.css` lines
~1083–1116) and `.neg` (`app/static/style.css` line 1217, a one-line
utility never pulled in before this phase needed it for negative-
variance/negative-net-income figures, same as `.dim`/`.mono`/`.small`
were each ported individually ahead of their own first caller).

**A real, previously-undiscovered backend bug, found and fixed in this
same commit**: `modules/reports/repository.py::budget_line_totals` —
`:date_from::date` (a bind param immediately followed by Postgres's `::`
cast operator, no space) reads to SQLAlchemy's `text()` parser as
something other than a plain named param, so the literal string reached
Postgres unsubstituted and raised a syntax error — but only when *both*
`date_from` and `date_to` are set, the one shape that hits both of the
function's conditional `where.append(...)` branches at once. No test in
`backend/tests/` had ever called this function at all before — it had
zero coverage of its own since Phase 1.4 — and no route had ever been
exercised with a real Compare-to against a real income-statement-only
(budget) scenario across a bounded date range until this screen's own
manual browser verification hit it live (`compare=BUD2026` in a real
browser, not a curl script). Fixed with a space before the cast
(`:date_from ::date`) — Postgres allows the whitespace, and it's enough
for SQLAlchemy to find the param boundary correctly; contrast
`cash_leg_net`'s own `COALESCE(:date_to, 'infinity'::date)` a few
functions up in the same file, whose `::date` casts a literal and so
never sat directly after a bind param name, which is why it never
tripped this. One new regression test,
`test_budget_line_totals_with_both_date_bounds_set` — confirmed to
actually fail against the pre-fix code (`git stash` the fix, rerun,
watch it fail with the exact same Postgres syntax error, `git stash
pop`), not just written and assumed to cover the bug. Same "this needed
a second fix once actually run against Postgres, not just reasoned
about" pattern Phase 1.5's `SET CONSTRAINTS` bug and Phase 1.8's
`ORDER BY` tiebreaker already taught — bundled into this commit rather
than split out, since the frontend screen genuinely cannot demonstrate
Compare-to without it (`CLAUDE.md`'s own bundling test: incoherent
apart).

Wired into `App.tsx`/`nav.ts` (`income_statement` → `/app/income-statement`).

**Verified for real**, same four checks as every screen this phase, plus
this is the first phase-4.1 screen to touch backend code so it also got
the exact CI shape by hand (a bare `postgres:16` container, `alembic
upgrade head`, `pytest` — 533 passed, up from 532). Real browser pass
covered both modes thoroughly: rows mode with no compare (five expense
root groups each producing their own cumulative "Net income after X"
row, hand-verified arithmetic all the way down to the final "Net
income"); rows mode with Compare to `BUD2026` (six real columns,
Scenario/Variance/%Variance/Compare, the Flip-variance-direction
checkbox appearing only once a compare scenario is picked, matching
legacy exactly) — this is what surfaced the `budget_line_totals` bug
live; and Split mode (`split=monthly` across a 3-month range with
Compare still set) — five period-column-groups (three real months plus
Total plus Average, each 4 sub-columns), the partial-period asterisk and
footnote on the still-in-progress current month, `.table-scroll`'s
horizontal scroll and sticky Code/Account columns, Total correctly
summing the two zero-activity months plus August's real figures,
Average correctly dividing Total by 3, and the account-tree collapse
toggle working identically inside the matrix table. Both `.csv`/`.xlsx`
exports (with `split`+`compare` both set) `200`ing over a real
authenticated `curl` round trip.

**Phase 4.1, screen 4 of 5 — Variance done.**
`frontend/src/reports/VariancePage.tsx` — the last Point-in-time report
of the four (`UI_CONSISTENCY_AUDIT.md` §2c's Ledger reclassification
puts it alongside Balance Sheet/Trial Balance/Ledger, not the range
reports), and the only one with a genuinely different row shape
depending on the request: native-depth (a real account tree, same
`flatten_tree()` shape Trial Balance/Balance Sheet use) vs. rolled-up (a
flat SQL-side aggregation with no `id`/`parent_id`/`depth` at all —
confirmed by reading `service.compute_variance` directly, not assumed).
No backend changes needed — `GET /reports/variance` has existed since
Phase 1.4/1.14.

**The same "let the id-less-row case degrade naturally" trick Balance
Sheet's synthetic rows already established, applied here to a whole
second row-shape rather than just a couple of rows**: `variance.html`'s
own row markup already handles both shapes uniformly by checking `r.id
is defined` — no `id` means no tree-toggle, no depth class, no
`data-id` — which is exactly what `useCollapsibleTree` already does for
an id-less row for free (never registered, so `isHidden` never hides it
and `toggle` never applies). So this page always runs every row through
the same `useCollapsibleTree` call, in both modes, with no branch of its
own — rolled-up mode simply has nothing collapsible, the same way
legacy's `report-tree.js` degrades on a `tr` with no `data-id`.

Two dropdowns worth noting: **Scenario/Compare-to have no "None"
option** (unlike Income Statement's Compare-to) — `variance.html`'s own
`<select>`s loop over every scenario with no blank choice at all, since
Variance always compares against *some* scenario (the service
auto-picks one if the request left `compare` blank). **The Compare-to
and Roll-up-to picker values are read from `result.compare`/`result.
level_id`, not the raw URL params**, once a result exists — `service.
compute_variance`'s own resolved values (an auto-picked compare
scenario, or a level defaulted from that scenario's own base level) can
differ from what the URL says, and the picker should reflect what
actually ran, the same "read the response back, not the request" rule
this phase's own Variance write-up in the plan called out ahead of time.
Confirmed live against `seed_demo.sql`: with no `compare` in the URL,
every non-staging/non-budget scenario turned out to be just `ACTUAL`
itself, so the service left `compare` genuinely blank (a real, legacy-
matching edge case, not a bug) — manually picking `BUD2026` and then a
real "Roll up to" level (`seed_demo.sql`'s `BUD2026` has no `base_level_
id` of its own, so the auto-default from decision path 2 in `compute_
variance`'s docstring never fires here) exercised the rolled-up branch
for real.

`useAccountLevels()` (already existed, Phase 3.4's `usePostableAccounts.
ts`) is reused as-is for the Roll-up-to picker's options — no new hook
needed.

Wired into `App.tsx`/`nav.ts` (`variance` → `/app/variance`).

**Verified for real**, same checks as every screen this phase (no
backend code touched, so no CI-shape rerun needed this time — 533 tests
unchanged). Real browser pass covered both row shapes: native-depth's
full tree (collapse/expand, depth indentation, chevrons) with a genuinely
blank Compare-to (confirmed correct per the paragraph above, not
mistaken for a bug); the rolled-up path selected by hand (real "Top
Level Accounts" rows, no indentation, no chevrons, `.neg` rendering
negative Liabilities/Equity/Income variances in red); and "Flip variance
direction" toggled live, correctly inverting sign and switching every
percentage between "—100.0%" and "100.0%" (matching the mathematically
exact (0−baseline)/baseline swap). Both `.csv`/`.xlsx` exports `200`ing
over a real authenticated `curl` round trip.

**Phase 4.1, screen 5 of 5 — Ledger done, and with it, Phase 4.1 itself is
complete.** The one screen this phase that needed real new backend work
first, not just a frontend screen against an already-existing route —
confirmed by exploration at the start of this phase: no `/ledger`-
equivalent, or any itemized-per-account-lines endpoint at all, existed
anywhere in `backend/`.

**Backend** (`modules/reports/`): `repository.py` gained
`ledger_accounts` (every postable, active account — `id`/`code`/`name`/
`account_type` only, ordered by type then code) and `ledger_lines`
(every individual debit/credit line posted in a scenario on or before
`as_of` — itemized, not aggregated, a plain SQL join since no Postgres
SRF returns per-line detail and none should be invented for a feature
legacy itself never needed one for — `REBUILD.md` decision 4).
`service.py` gained `ledger_rows`, ported from legacy `_ledger_rows`
unchanged in shape: one T-account card per account with activity (or
every account, with `zeros`), pairing debits and credits by index into
display rows, a running total that writes to only one of Debit/Credit
per card, and the same raw/simulated-close carve-out Trial Balance
applies to Income/Expense lines — here applied per *line* rather than to
an aggregate balance. `router.py` gained `GET /reports/ledger`, matching
every other point-in-time route's shape (`scenario`/`as_of`/`zeros`/
`raw`, `prev_as_of`/`next_as_of`/`today`) — **no `.csv`/`.xlsx` export
siblings**, since legacy's own `ledger.html` never had them and nothing
here should invent behavior legacy never had. 9 new backend tests (4
`test_repository.py`, 3 `test_service.py` — including one purpose-built
fresh-scenario test proving the raw/simulated-close carve-out applies to
Income/Expense lines but never to Asset/Equity lines from the same prior
month, which the shared `book` fixture's own dates couldn't exercise — 2
`test_router.py`, one of which asserts the *absence* of export routes) —
542 passed total, up from 533.

**Frontend**: `frontend/src/reports/LedgerPage.tsx` — the only screen
this phase with a genuinely different layout: a wrapped grid of small
T-account cards (Date | Debit | Credit | Date), one per account, instead
of one wide report table. No account hierarchy, no `useCollapsibleTree`
(same reasoning Cash Flow's own flat sections already established).
Caught and avoided, not repeated, a real bug class from the 2026-08-30
QA pass: the "Show accounts with no activity" link (shown only on the
empty-state message) is a real `<Link>`, not a `<button className=
"button-link">` — `.button-link`'s CSS targets `a.button-link`
specifically, the exact mismatch that pass already found and fixed
eight times over for other screens.

New CSS ported: `.t-account-section`/`.t-section-label`/
`.t-account-grid`/`table.ledger.t-account`/`.t-divider` (the T-account
card styling, `app/static/style.css` lines ~1161–1205 — confirmed
missing by grep, same byte-verified-range practice every visual phase
uses).

Wired into `App.tsx`/`nav.ts` (`ledger` → `/app/ledger`) — the fifth and
last of Phase 4.1's sidebar links to flip from a legacy bare-path `<a>`
to a real client-side `<Link>`.

**A mechanical step worth noting for future backend-adding phases**:
adding a new backend route means `frontend/src/api/schema.ts` (the
typed OpenAPI client, generated once and committed, not regenerated at
build time) goes stale — `tsc` catches this immediately and loudly
(`Argument of type '"/reports/ledger"' is not assignable to parameter of
type 'PathsWithMethod<paths, "get">'`), so there's no way to silently
ship a frontend call against a route the generated client doesn't know
about yet. Regenerated via `frontend/package.json`'s own `generate:api`
script (`python scripts/dump_openapi_schema.py` from `backend/`, piped
into `openapi-typescript`, run through the same throwaway
`node:22-slim` container this session already uses for `oxlint` since
this machine has no local `node`/`npm`).

**Verified for real**, same checks as every screen this phase, plus the
exact CI shape by hand (bare `postgres:16`, `alembic upgrade head`,
`pytest` — 542 passed) since this is the one screen with new backend
code. Real browser pass: the full T-account card grid rendering
correctly for every postable account with real activity (Checking's own
card total-debit, 48,949.51, matching Balance Sheet's own figure for the
same account and as-of date exactly); no Export CSV/XLSX links anywhere
on the page (confirmed by search, matching legacy's real absence, not an
oversight); the empty-state message and its "Show accounts with no
activity" link correctly carrying `as_of` forward while adding
`zeros=1`; and that link's target actually rendering every postable
account as an empty card once followed.

**Phase 4.1 is now fully done** — all five screens shipped, verified,
and documented. **Next up: Phase 4.2** (remaining Management/CRUD:
payees, scenarios, account_levels, scheduled, entry_templates,
settings), which reuses `useSelectMode.ts`/`MergeDialog.tsx` from Tags
(Phase 3.2), the same reuse Trial Balance/Balance Sheet/Income
Statement/Variance already proved out for the Point-in-time/Range-report
archetypes this phase.

**Phase 4.2, screen 1 of 6 — Payees done.** `frontend/src/setup/
PayeesPage.tsx`, ported from `app/templates/payees.html` +
`entity-manage.js`. No new backend work at all — `modules/reference/`
(router, service, repository, schemas) already carried every route this
screen needs (`GET/POST /payees`, `.../rename`, `.../toggle-active`,
`.../delete`, `.../merge`), left over from when Accounts/Account levels/
Scenarios/Payees/Tags were bundled into one module rather than being
Tags-only. Structurally almost identical to `TagsPage.tsx`
(Phase 3.2) — same Select/Merge bar (`useSelectMode.ts`/
`MergeDialog.tsx`, reused unchanged, confirming that hook's own Phase 3.2
comment that it was written generic on purpose), same inline-rename-
input/Archive/Delete row shape — with three real differences, not a
generic abstraction of the two: name is `maxlength="80"` here, not 40
(payees.html's own input, vs. tags.html's 40); the entry-count cell is a
real drill-through `<Link>` to the Journal (`/app/entries?payee=...`),
unreachable from TagsPage.tsx (Phase 3.2 predates Journal existing) but
real now that `JournalPage.tsx` (Phase 3.4) already reads `?payee=` —
still no `back=`, matching JournalPage.tsx's own standing deferral; and
no quick-create route rendered on this page (`POST /payees/quick-
create` is `usePayees.ts`'s own Journal-combobox route, not this
table's). Wired into `App.tsx` (`/app/payees`, `routeKey`,
`PAGE_TITLES`) and `nav.ts` (Setup group, `client: true`, same pattern
every other Phase 3/4 screen already followed).

Verified with a real `docker compose up -d --build` (`backend/docker-
compose.yml`): clean `tsc -b && vite build`, `oxlint` 0 warnings/errors,
then browser-driven end to end against the running container — add,
archive, unarchive, and delete all round-tripped correctly (flash
copy matches legacy's own strings verbatim, including the delete
confirm's "Entries that used it will lose the payee label" wording);
rename's own submit path confirmed via `form.requestSubmit()` (this
sandbox's synthetic Enter keypress doesn't trigger a browser's implicit
single-text-field form submission — confirmed to be a pre-existing
harness quirk, not a regression, by reproducing the identical non-
submission on the already-shipped TagsPage.tsx first).

**Phase 4.2, screen 2 of 6 — Scenarios done.** `frontend/src/setup/
ScenariosPage.tsx`, ported from `app/templates/scenarios.html`, no
vanilla-JS counterpart beyond the inline `<script>` toggling two form
fields when "income statement only" is checked (ported as a plain
conditional render instead of a DOM `hidden` flip). No backend work —
same `modules/reference/` leftover-bundling `PayeesPage.tsx`'s own
write-up already explains. Structurally unlike Payees/Tags on purpose,
not by omission: legacy's own table has exactly one per-row action
(Lock/Unlock, no rename/archive/delete), and the "add" UI is a
permanent `<div class="panel">` form, not a collapsible `<details>` —
so this page has no Select/Merge bar and doesn't reach for
`useSelectMode.ts`/`MergeDialog.tsx` at all, unlike every other 4.2
screen so far. Reuses `useAccountLevels()` (`api/useAccountLevels.ts`)
for the "Base level" picker — exactly the second caller that hook's own
Phase 3.4 comment predicted.

One real default worth flagging: the create form's "require balanced
entries" checkbox starts unchecked, matching `scenarios.html`'s own
checkbox with no `checked` attribute — even though `schemas.
CreateScenarioRequest.enforce_balance` defaults to `True` at the
Pydantic layer. No conflict in practice: a controlled checkbox always
sends an explicit `false` on first submit, same as a legacy form POST
with the box left unticked; the schema default only ever matters for a
request that omits the field entirely, which this page's own submit
handler never does.

Verified with a real `docker compose up -d --build`: clean `tsc -b &&
vite build`, `oxlint` 0 warnings/errors, then browser-driven against the
running container (real seed data, not empty tables) — the three
existing scenarios (Actual/Budget 2026/Staging) rendered with correct
Kind/Balance rule/Base level derivations for all three real shapes
(full ledger, income-statement-only, staging); the income-statement-only
checkbox correctly hid/showed the balance-rule and base-level fields;
created a real scenario end to end (defaults verified: `budget` type,
"single-sided OK", "leaves only"); Lock/Unlock round-tripped and flipped
the status badge. No console errors.

**Phase 4.2, screen 3 of 6 — Account levels done.** `frontend/src/setup/
AccountLevelsPage.tsx`, ported from `app/templates/account_levels.html`
— no vanilla-JS counterpart at all. A third distinct shape from Payees/
Scenarios: the rename input is permanently visible right in the row
(a plain text input + "Save" button, not TagsPage.tsx's click-to-edit
toggle and not Scenarios' single Lock/Unlock action), so this page
carries no `editingId` state either. `next_depth` (the New level form's
own default) isn't a backend field — ported as `Math.max(0, ...depths) +
1` computed from the same `GET /account-levels` response, matching
legacy `app/main.py`'s identical `max(depths, default=0) + 1`, since no
route returns it as one either.

Verified with a real `docker compose up -d --build`: clean `tsc -b &&
vite build`, `oxlint` 0 warnings/errors, then browser-driven against the
running container with real seed data (3 levels: Top Level Accounts/
Subaccounts/Account Detail) — next_depth correctly showed 4; created a
throwaway 4th level (next_depth then correctly advanced to 5, not
reused), renamed it, and deleted it, watching next_depth fall back to 4
each time rather than mutating the three real seeded levels; the delete
confirm's copy matches legacy's own `Delete level {name}?` verbatim. No
console errors.

**Phase 4.2, screen 4 of 6 — Scheduled entries done.** `frontend/src/
setup/ScheduledPage.tsx`, ported from `app/templates/scheduled.html`.
The first screen this phase that needed real line-entry UI, not just a
table plus a couple of scalar fields — legacy's own template shares one
`app.js` between this page and `entries.html`'s New entry panel, so this
reuses `journal/EntryGrid.tsx` and `journal/gridLines.ts`
(`makeBlankLine`/`ensureTrailingBlank`/`isLineUsed`) unchanged, and
mirrors `NewEntryPanel.tsx`'s own state/handlers (account-by-scenario
refiltering via `usePostableAccounts()`, Distribute, the payee quick-
create combobox, Alt+N/D/S shortcuts via `e.code`) rather than
reinventing them. Three real differences from that panel, not a shared
abstraction: a permanent `<div class="panel">`, not a collapsible
`<details>` (so no Alt+E, no `defaultOpen`); Repeats-every/unit/Next-on
replace a single Date field, and Save is disabled on `!balanced` alone —
`modules/scheduling/service.py::create_schedule`'s own `total != 0`
check is unconditional, unlike the Journal's scenario-dependent
`enforce_balance`, though the "(single-sided OK)" scenario-label suffix
is kept since it still describes a real property of that scenario, just
not a rule this form's own Save button honors; and no Clear button/
Alt+C — legacy's own button row here only ever had Save/Add line/
Distribute. The `pending_count` Staging banner is deliberately not
ported yet — noted inline, revisit at Phase 4.3 once Staging exists to
read and link to.

Verified with a real `docker compose up -d --build`: `tsc -b && vite
build` needed one real fix first (`oxlint`'s `react(set-state-in-effect)`
on an effect that synced `scenarioId` to the first-loaded scenario once
`scenarios` arrived — fixed by deriving `scenarioId` from
`explicitScenarioId ?? firstScenarioId` during render instead of
syncing via `setState` inside a `useEffect`), clean after; then
browser-driven against the running container with real seed data — the
account combobox on the grid correctly listed the selected scenario's
own postable accounts, Distribute correctly filled the second row's
credit to balance the first row's debit, and a real schedule saved end
to end. One real surprise, not a bug: the newly created schedule's
`next_date` (submitted as today) showed as one month later immediately
after creation — `main.py`'s own `advance_due_schedules` middleware
(wired at Phase 1.14, despite `modules/scheduling/service.py`'s own
docstring on `materialize_due_schedules` still saying "not wired into
anything yet" — a stale comment worth fixing on a future pass through
that file) runs `materialize_due_schedules` on every authenticated
request, so a same-day schedule gets staged and its `next_date`
advanced before the page's own post-save reload even completes.
Confirmed by reading `scheduled_entries` directly in the container's
Postgres, not assumed. Archived the test schedule afterward. No
console errors.

**Phase 4.2, screen 5 of 6 — Entry templates done.** `frontend/src/
setup/EntryTemplatesPage.tsx`, ported from `app/templates/
entry_templates.html`. Same `EntryGrid.tsx`/`gridLines.ts` reuse
`ScheduledPage.tsx`'s own write-up already explains, and simpler than
either that page or `NewEntryPanel.tsx` in one real way: entry templates
aren't scenario-bound at all, so there's no Scenario field and the
account picker uses `usePostableAccounts()`'s own `forPickers` (the
union across every scenario) — exactly the case that field's own Phase
3.4 docstring names as its reason for existing ("entry_templates.html
isn't scenario-bound"). Balance is still unconditionally required
(`create_template`'s own `total != 0` check, identical to
`create_schedule`'s), and Delete (not archive — `entry_templates` has no
`is_active` column) is the one row action.

Verified with a real `docker compose up -d --build`: clean `tsc -b &&
vite build` and `oxlint` on the first pass this time (the `set-state-
in-effect` fix from Scheduled entries carried over as a pattern rather
than a mistake repeated); then browser-driven against the running
container — the account combobox correctly offered every scenario's
postable accounts unfiltered (typing "Rent" found `5110 · Rent /
Mortgage Interest`, not scoped to any one scenario), Distribute
balanced a real two-line template, and it saved end to end. Confirmed
the actual cross-screen integration this screen exists for, not just
this screen in isolation: opened the Journal's own New entry panel
right after, and the just-saved "Monthly Rent" template appeared in its
"Load template" picker and populated the grid correctly on selection —
description, both accounts, and both amounts all correct. Delete
confirm copy matches legacy's own `Delete template {name}?` verbatim.
Deleted the test template afterward. No console errors.

**Phase 4.2, screen 6 of 6 — Settings done. Phase 4.2 is now fully
done.** `frontend/src/setup/SettingsPage.tsx` (the hub, ported from
`app/templates/settings.html`) and `frontend/src/setup/
SettingsAccountPage.tsx` (the username/password form, ported from
`app/templates/account.html`, split into its own `/app/settings/account`
route exactly like legacy's own separate template). Reads differently
from every other screen this phase built — a hub of small, mostly
independent panels, not one CRUD entity — and needed two genuinely new
pieces of infrastructure that nothing before this screen had a caller
for:

- `frontend/src/format/date.ts` — a `formatDate(iso)` function mirroring
  `format/money.ts`'s exact contract (reads `postwarden-date-format`
  fresh on every call, default `iso`), now wired into the five real
  screens legacy's own `dateformat` Jinja filter actually reached that
  are already built: Journal, Ledger (both date columns), Cash Flow,
  and Scheduled entries. Found the authoritative list by grepping
  legacy's own templates for the filter rather than trusting
  `settings.html`'s summary blurb, which omitted Ledger and Cash Flow.
  Report "As of" headers and month-nav links deliberately stay
  unformatted — confirmed via the same grep that legacy never applied
  the filter there either.
- `frontend/src/format/centsEntry.ts` — a verbatim port of
  `cents-entry.js`'s `document`-level delegated listener (not a
  DOM-rewrite-to-plain-function port like `date.ts`/`money.ts`; legacy's
  own shape was already exactly right for a global initializer), wired
  once from `main.tsx` outside React entirely, the same reasoning
  `index.html`'s own pre-paint theme/font script already established.
  `EntryGrid.tsx`'s debit/credit inputs already carried the `amount`
  className this listens for (Phase 3.4, before this file existed), so
  it covers Journal/Scheduled/Entry templates' grids for free.

The rest of `SettingsPage.tsx` writes to mechanisms that already
existed before this screen — `postwarden-theme`/`postwarden-font`
(`index.html`'s pre-paint script, Phase 2.4) and
`postwarden-number-format` (`format/money.ts`, Phase 3.3) — this is the
first thing that ever *writes* any of those three keys rather than only
reading them.

**Two real bugs found in manual verification, both fixed before
committing:**

1. `centsEntry.ts`'s `setFromCents` set `field.value` directly, then
   dispatched a plain `new Event('input', {bubbles: true})`. React DOM
   installs a value tracker on every `<input>` instance specifically so
   its change-event plugin can tell a real change from a no-op; a plain
   assignment through the instance's own overridden setter updates that
   tracker's recorded value *before* the dispatched event is compared
   against it, so React never sees a diff and `onChange` never fires.
   The field visibly showed the shifted digits ("62.00") while
   `EntryGrid`'s totals bar — driven by React state — stayed stuck at
   whatever it was before. Fixed by calling the *prototype's* value
   setter directly (`Object.getOwnPropertyDescriptor(HTMLInputElement
   .prototype, 'value').set`), the standard workaround: it bypasses
   React's instance-level override, so the tracker still holds the old
   value when the event fires and correctly detects the change.
   Confirmed with real single-keystroke `computer` actions (not the
   batch `type` action, which turned out to use CDP text insertion that
   bypasses `keydown` entirely — a testing-tool quirk, not related to
   this bug) against a live Scheduled entries grid: `6`→`0.06`,
   `2`→`0.62`, `0`→`6.20`, `0`→`62.00`, then Backspace→`6.20`, with the
   DEBITS total tracking correctly at every step.
2. `SettingsAccountPage.tsx`'s username `<input pattern="[a-z0-9_.-]
   {3,32}">` threw `Invalid regular expression: ...: Invalid character
   in character class` in the console on every render — current Chrome
   compiles the `pattern` attribute in unicode-sets (`v`-flag) mode,
   where a trailing unescaped `-` in a character class is no longer
   auto-literal the way plain-regex mode always treated it, and the
   native pattern check silently stops validating anything as a result.
   `tsc`/`oxlint` see a plain string, so neither caught it. Fixed by
   escaping the hyphen (`[a-z0-9_.\-]{3,32}`); confirmed the console is
   clean on a fresh tab and that submitting an invalid username (`AB` —
   too short, uppercase) is now correctly blocked client-side without a
   network request. `modules/auth/service.py`'s own `USERNAME_PATTERN`
   still owns the real validation either way.

Also found, not a bug in this screen's own code but in session state
management: `SettingsAccountPage.tsx`'s successful username change
updated only its own local state, so `Topbar.tsx`'s username link (and
`SettingsPage.tsx`'s own "Signed in as") stayed stale until the next
full `GET /me` — confirmed by renaming to `davidtest` and watching the
topbar keep showing `david` until a hard reload. Fixed by adding
`setUsername` to `SessionValue`/`SessionProvider.tsx` (updates the
in-memory `user.username` directly, no round trip) and calling it from
`submitUsername`'s success handler alongside the existing local-state
update. Confirmed live: the topbar now updates the instant the flash
message appears, no reload.

Verified with a real `docker compose up -d --build`, twice (once after
the initial build, once after each bug fix above) — clean `tsc -b &&
vite build` and `oxlint` every time. Browser-driven against the running
container: Theme and Font both apply live and persist across reload
(Font visually confirmed — Classic Serif noticeably changes headings and
body text); the Amount entry checkbox toggles `postwarden-cents-entry`
correctly (native-label-click, since `form_input` on a checkbox doesn't
reliably fire React's `onChange` — a known controlled-checkbox caveat,
not specific to this screen); Number & date format panel confirmed
end-to-end against real consumer screens, not just localStorage — set
Symbol to `$` and Date format to `us`, then loaded Journal (amounts
showed `$22.50`, dates showed `08/31/2026`) and Ledger (`$25,000.00`,
`08/01/2026` in both date columns) and confirmed both formats applied;
reverted all test preferences to defaults afterward. `SettingsAccountPage
.tsx`'s full password-change round trip run for real against the local
dev account (with the user's explicit go-ahead first): changed
`devpassword`→`devpasswordtest`, watched the "Password changed — signing
you out…" flash and the forced logout land on `LoginPage` after the
1.5s delay, logged back in with the new password (SPA correctly
returned to the same `/app/settings/account` route once authenticated),
then changed the password back to `devpassword` and logged in once more
— restoring the exact `david`/`devpassword` pair `CLAUDE.md` documents,
confirmed clean at the end. No console errors on a fresh tab for either
screen.

Phase 4.2 is now fully done — all six screens (Payees, Scenarios,
Account levels, Scheduled entries, Entry templates, Settings) built,
verified, and documented. Next up: Phase 4.3 (Staging).

### Phase 4.3 — Staging

Ported from `app/templates/staging.html` + `staging.js`/`staging-inline-
edit.js` (Phase 4.3) — the Filterable transaction list archetype's
second instance, `UI_CONSISTENCY_AUDIT.md` §4b's own call ("already the
target shape; no change proposed") confirmed rather than revisited.
`modules/staging/` (backend) was already fully built and tested back in
Phase 1.6/1.14 — this phase is frontend-only, two new files:
`staging/StagingPage.tsx` and `staging/StagingEditPanel.tsx`, plus a
small `staging/useStagingPendingCount.ts` addendum (below).

**Real reuse, not a rewrite of shapes that already exist.**
`DescriptionCell.tsx`/`MemoCell.tsx`/`BulkTagsDialog.tsx` (all
`journal/`) are imported into `StagingPage.tsx` unchanged — the routes
they call (`/entries/{id}/edit-description`, `/entries/lines/{id}/edit-
memo`, `/entries/tags`) carry no `is_staging` condition at all
(confirmed directly in `modules/entries/repository.py`), matching
`docs/ARCHITECTURE.md`'s own note that this parity is real, not
incidental. `EntryGrid.tsx`/`gridLines.ts` (also `journal/`) are
`StagingEditPanel.tsx`'s own line grid — the same cross-folder reuse
`ScheduledPage.tsx`/`EntryTemplatesPage.tsx` already established in
Phase 4.2, not a new pattern.

**Real differences from the Journal, forked rather than shared** (same
"a screen should be deletable on its own" reasoning `modules/staging/
repository.py`'s own docstring gives for forking its backend filter
fragments): Scenario here filters each entry's own *target* scenario
(where it lands once approved — `target_scenario`, ported straight off
`build_filter`'s own query param), not the scenario it's posted in,
since every row already shares the one real Staging scenario. No hide-
reversed checkbox (a pending entry can't be a reversal), no entry_id/
account/payee "Showing only…" banners (nothing drills into Staging with
those query params the way a report drills into the Journal), no
Export/pager (`list_pending` was never paginated, matching legacy
exactly). Approve/Reject replace Reverse and stay visible-but-disabled
throughout rather than select-only — ported verbatim, same "read what
they do without discovering Select first" reasoning legacy's own
comment gives for those two specifically. Confirm wording for both
(including bulk Reject's `danger` styling) is copied verbatim from
`staging.js`'s own `msg` computation.

**`StagingEditPanel.tsx`** is the one genuinely new component — the
per-entry "Edit" grid, relocated in place of an entry's `.staging-view`
once "Edit" is clicked, same in-place-swap `staging-inline-edit.js`
already did rather than a separate page. It mirrors `NewEntryPanel.tsx`'s
own state/handlers (`updateLine`/`addRow`/`distribute`/the balance bar)
rather than factoring a shared hook out of the two — the same call
`ScheduledPage.tsx`'s own Phase 4.2 write-up already made for the
identical shape, for the same reason (real, small differences, not
worth an abstraction). Three differences from `NewEntryPanel.tsx`,
recorded in its own file comment: no scenario picker (fixed by whatever
produced the staged entry, read off `GET /staging/{id}/edit`'s own
`target_scenario_id`, with `enforce_balance` looked up against the
`scenarios` list already in scope rather than legacy's `sr-only
<select>` trick, which existed only so `app.js`'s shared code had *a*
scenario element to read `data-enforce` off); loads existing data
instead of starting blank (`isZeroAmount` tells a real 1-cent leg apart
from `journal_lines`' own `NUMERIC NOT NULL DEFAULT 0` zero side before
blanking it back out for the input — `entry_templates` lines have no
such column default, so `EntryTemplatesPage.tsx`'s own load path never
needed this check); no template loader, no Clear, no Alt+E (the panel
is always already open by the time it mounts).

**One addendum to a Phase 4.2 screen, closing a forward reference that
phase's own write-up left open on purpose:** `ScheduledPage.tsx`'s file
comment explicitly deferred porting legacy's `pending_count` Staging
banner ("Staging itself doesn't have a JSON shape this page has ever
read yet… revisit once Phase 4.3 gives this page something real to read
and link to"). It now does — `useStagingPendingCount.ts` is a small
one-shot hook reading `GET /staging`'s own `entries.length` (no bespoke
count endpoint needed; `list_pending` was never paginated, so the full
list is cheap enough for a personal ledger's queue), and the banner
links to `/app/staging`, a real client route now instead of the bare
`/staging` JSON response the deferred comment pointed at. Likely second
caller: the Dashboard's identical banner (Phase 4.7).

**Routing**: `nav.ts`'s Staging link becomes `client: true` /
`/app/staging` (was a plain `/staging` full-page navigation into raw
JSON); `App.tsx` gained the route, `routeKey`, and `PAGE_TITLES` entries,
same three-line pattern every prior Phase 4 screen added.

**Verified two ways.** First, `tsc -b && vite build` and `oxlint` both
clean — run inside a throwaway `node:22-slim` container (`docker run
--rm -v "$PWD":/repo -w /repo node:22-slim sh -c "npm ci && npm run
build"`), since this machine has no Node on `PATH` at all outside the
Dockerfile's own build stage (`backend/Dockerfile`'s "No Node at
runtime" design, confirmed as the reason, not a gap). Second, a real
`docker compose -f backend/docker-compose.yml up -d --build backend`
followed by an **authenticated** round trip against the running
container (per this repo's own "an unauthenticated sweep proves
nothing" deploy-checklist rule) — logged in as `david`/`devpassword`,
then: `GET /staging` listed a real pending schedule-materialized entry
sitting in the dev DB; `GET /staging/{id}/edit` matched
`StagingEditPanel.tsx`'s own `EditData` interface field-for-field;
`POST /staging/{id}/edit` with the exact body shape the component sends
(added a line memo) round-tripped correctly on a follow-up `GET`;
`POST /staging/approve` posted it for real into `ACTUAL`, confirmed via
`GET /entries?entry_id=<new id>` showing the new entry with the memo
carried over and `posted_by: "david"`; a follow-up `GET /staging`
correctly came back empty; `GET /staging/duplicates` returned
`{"groups": []}` cleanly with nothing pending. No interactive browser
tool was available in this session, so hover states, keyboard shortcuts
(Alt+A/Alt+R/Alt+N/Alt+D/Alt+S), and focus management were not visually
exercised the way this repo's own standing verification checklist asks
— worth a manual pass before Phase 4.4.

**Unrelated, and reverted, not part of this commit**: `git status` at the
start of this phase's work showed an unexplained uncommitted change to
`frontend/src/format/shortcut.ts` (`altLabel`'s `` `⌥${letter}` `` had
become the literal string `` `⌥+{letter}` `` — a real regression, not a
formatting nit, that would have broken every Mac/iPad Option-key shortcut
label). Neither this session nor its own tool history produced that
edit; reverted via `git checkout -- frontend/src/format/shortcut.ts`
before committing Balance Sheet, so it isn't bundled in here. Flagged to
David directly rather than silently discarded, in case it was
in-progress work from elsewhere that shouldn't have been touched.

---

## Phase 0 — Scaffolding

Not one of `REBUILD.md` §6's five numbered phases, but has to happen
before any of Phase 1's code does. Pure setup, no product logic.

- [x] **0.1** Create the `backend/src/postwarden/` tree per `REBUILD.md`
      §6 (`domain/`, `modules/`, `export/`, `analytics/`, `main.py`,
      `config.py`, `db.py`) — empty packages first, so the directory
      shape is settled before anything fills it in. `main.py` carries a
      trivial `/healthz` route (no DB touch) as the one bit of real code,
      to prove the container actually boots; `config.py`/`db.py` are
      still docstring-only stubs, deferred to 1.2.
- [x] **0.2** Pick and pin backend dependencies (FastAPI, SQLAlchemy
      Core, Alembic, Pydantic v2, pytest, psycopg driver, uvicorn) —
      recorded in `backend/pyproject.toml` (`src`-layout package, `dev`
      extra for pytest/httpx). Same major versions as legacy
      `requirements.txt` where the tool carries over.
- [x] **0.3** Decided: **fully separate** dependency files — see log
      below. The premise for a shared file ("they'll run as two
      containers side by side") no longer holds now that decision 6 was
      reversed: `master`'s app isn't run anywhere during this rebuild,
      including locally, so there's no drift to manage between two live
      dependency sets — just one frozen file and one active one.
- [x] **0.4** `alembic init`, baseline revision generated from the
      current `db/schema.sql` (`REBUILD.md` decision 5). Confirm
      `alembic upgrade head` against a fresh database reproduces
      `schema.sql` with no diff.
- [x] **0.5** GitHub Actions CI workflow: `pytest` against a Postgres
      service container. The repo has no CI today — this is new, not a
      port. Lands empty-green (no modules yet) so every subsequent PR is
      checked from the start.
- [x] **0.6** `docker-compose` service for the new backend's own
      database volume, loaded with `schema.sql` + `seed.sql` +
      `seed_demo.sql`. Confirm it comes up clean from a fresh
      `docker compose up -d --build` after `down -v`. No legacy Jinja
      service needs to run alongside it — `master` is a git-level
      fallback only, not standing infrastructure (`REBUILD.md`
      decision 6).

## Phase 1 — Backend restructure

Order matters here: pure domain logic first (fastest to verify, no
database), then the hard report math (where correctness risk actually
lives), then the mechanical CRUD bulk. See `REBUILD.md` §4's "Genuinely
hard / Mechanical / Effectively free" table — this ordering follows it
directly.

- [x] **1.1** `domain/money.py`, `periods.py`, `accounts.py`, `entry.py`
      — pure logic, zero framework/IO imports. Unit tests only, no DB,
      no FastAPI.
- [x] **1.2** `config.py` + `db.py` — settings and the SQLAlchemy Core
      engine/session setup.
- [x] **1.3** Central `Decimal`/`date` JSON encoder, fixed once here
      rather than per-route. Documented gap, not theoretical — the
      current app hand-rolls workarounds twice (`staging_duplicates_page`'s
      `groups_json`, `templates_full()`).
- [x] **1.4** `modules/reports/` — the ~450 "genuinely hard" lines,
      ported **with comments and docstrings intact**:
      `_build_account_tree`/`_flatten_tree`, `_income_statement_matrix`/
      `_scale_income_statement_result`, `_cash_flow_rows`/
      `_cash_flow_tie_out`, `_compute_variance`, `_split_periods`. Keep
      calling the existing Postgres SRFs (`fn_trial_balance`,
      `fn_cash_flow_lines`, `fn_rollup_balance`, `fn_account_balances`)
      directly — **not** modeled through SQLAlchemy Core (decision in
      `REBUILD.md` §6).
- [x] **1.5** `modules/entries/` (router · schemas · service ·
      repository · tests) — the Journal backend.
- [x] **1.6** `modules/staging/`
- [x] **1.7** `modules/budget/`
- [x] **1.8** `modules/imports/` — both importers (plain CSV and the
      mapped/rules importer).
- [x] **1.9** `modules/reference/` — accounts, payees, tags, scenarios,
      account levels (CRUD).
- [x] **1.10** `modules/scheduling/` — scheduled entries, entry
      templates.
- [x] **1.11** `modules/auth/`
- [x] **1.12** `export/` — shared CSV/XLSX writers, consumed by
      `entries` and `reports` (not `imports` — that module only ever
      *reads* a CSV, it never writes one, so it has no reason to depend
      on this package; corrected on completion, see the Current status
      write-up). XLSX carries live Excel formulas (cell-by-cell sums,
      not ranges) — ported deliberately, not incidentally.
- [x] **1.13** `analytics/` — star-schema views + the documented
      `/api/*` contract (the 5 existing routes).
- [x] **1.14** `main.py` cut down to app factory + router mounting only.
- [x] **1.15** **Gate:** the 60 pure-Postgres tests
      (`tests/test_invariants.py`, `tests/test_cashflow.py`) pass
      unchanged, and every ported module's own tests are green in CI.
      Frontend work does not start before this.

## Phase 2 — Frontend foundations

- [~] **2.1** Vite + React + TypeScript scaffold under `frontend/`,
      built output served by FastAPI `StaticFiles`. Confirm no Node
      process is required at runtime. Scaffold built, wired into
      `main.py`, verified outside Docker (real `npm run build` + real
      `uvicorn` serving it, full backend suite green); the
      `docker compose up -d --build` confirmation itself is blocked in
      this sandbox — see Current status and Open questions.
- [x] **2.2** Typed API client generated from the backend's OpenAPI
      schema — `openapi-typescript` + `openapi-fetch`, see the Current
      status write-up.
- [x] **2.3** Port the 327 CSS custom properties and 21 themes from
      `app/static/style.css`, essentially verbatim.
- [x] **2.4** Shell: sidebar (hover-preview + click-to-pin, three
      collapsible groups), topbar, flash banners, and the pre-paint
      theme/font restore script that currently prevents FOUC via an
      inline `<head>` script.
- [x] **2.5** Per-widget decision, recorded here as it's made — Radix/
      shadcn vs. porting the existing JS — for combobox, datepicker,
      confirm dialog, number-stepper. Each existing widget encodes a
      real fix (`e.code` for Option-remapped keys, explicit `tabIndex`
      for Safari, the iOS `select()` no-op) that an off-the-shelf
      component won't reproduce for free.

## Phase 3 — One screen per archetype (the go/no-go gate)

Ascending risk, per `REBUILD.md` §6:

- [x] **3.1** login — proves the pipeline end to end
- [x] **3.2** tags — Management/CRUD archetype
- [x] **3.3** trial balance — Point-in-time report archetype
- [x] **3.4** Journal — the hardest screen in the app

**Gate outcome: pass — proceed to Phase 4.** Ported to
`frontend/src/journal/` (`JournalPage.tsx`, `NewEntryPanel.tsx`,
`EntryGrid.tsx`, `BulkTagsDialog.tsx`, `DescriptionCell.tsx`,
`MemoCell.tsx`, `gridLines.ts`), plus `widgets/TagInput.tsx` and
`widgets/useInlineEdit.ts`. Clearly better than the Jinja version on the
axis that actually matters here: the entry grid, filter bar, description/
memo edits, and Select/Reverse/Edit-tags are all one component tree
sharing real state, replacing ~1,240 lines of hand-wired DOM scripting
(`app.js` + five smaller files) and a page-reload-plus-`fetch()` model
with plain React re-renders — no `data-*` attribute wiring, no delegated
document-level listeners standing in for what props/state already give
for free. See Current status for the full write-up.

## Phase 4 — Fill in by archetype

Largely configuration once the Phase 3 archetype components exist.

- [x] **4.1** Remaining Range/period + Point-in-time reports:
      income_statement, cash_flow, balance_sheet, variance, ledger. All
      five done — see Current status. Ledger needed real new backend
      work (`modules/reports/repository.py::ledger_lines`/
      `ledger_accounts`, `service.ledger_rows`, `GET /reports/ledger`),
      the only screen this phase that wasn't just frontend against an
      already-existing route.
- [x] **4.2** Remaining Management/CRUD: payees, scenarios,
      account_levels, scheduled, entry_templates, settings. All six
      done — see Current status. Settings needed two new pieces of
      client-side infrastructure (`format/date.ts`, `format/
      centsEntry.ts`) and turned up two real bugs (a React value-tracker
      bypass in the cents-entry mechanism, an unescaped hyphen in a
      `pattern` regex under Chrome's newer `v`-flag compilation) plus a
      stale-session-state gap (`SessionValue` gained `setUsername`), all
      fixed and verified before this phase closed.
- [x] **4.3** staging (Filterable transaction list, second instance) —
      backend already done (Phase 1.6/1.14); frontend-only this phase.
      `StagingPage.tsx` reuses `JournalPage.tsx`'s own `DescriptionCell`/
      `MemoCell`/`BulkTagsDialog` unchanged, `StagingEditPanel.tsx` is the
      one new component (mirrors `NewEntryPanel.tsx`, same "not a shared
      abstraction" call `ScheduledPage.tsx` already made). Also closed a
      forward reference from Phase 4.2: `ScheduledPage.tsx` now has its
      pending-Staging banner. See Current status for the full write-up.
- [ ] **4.4** budget (Editable grid archetype)
- [ ] **4.5** staging_duplicates
- [ ] **4.6** accounts
- [ ] **4.7** The rest: dashboard, connect_bi, import, import_mapped,
      import_mapped_review, account, help

## Phase 5 — The long tail

This is where rebuilds overrun — budgeted for explicitly, per
`REBUILD.md` §6. Track each item's completion independently; expect this
list to grow as items are discovered, not just shrink.

- [ ] 21 themes × 26 screens visual pass
- [ ] Every `Alt+`/`e.code` shortcut, plus `option-key.js`'s ⌥
      relabeling on Apple hardware
- [ ] Confirm dialogs: focus Cancel by default, trap Tab between exactly
      two buttons, red reserved for genuinely destructive actions
- [ ] Debounced-autosave-with-corrective-POST on memo/description edit
      (Escape must undo a draft that already reached the server)
- [ ] Tri-state (indeterminate) select-all on five screens, clearing
      selection when Select mode turns off
- [ ] Per-thing `localStorage` keys (per sidebar group, per report
      table, per budget scenario) — collapsing one must never reset
      another
- [ ] Report tree defaults differ by page (Accounts collapsed-first,
      reports expanded-first)
- [ ] Distinct empty states per condition (nothing exists vs. nothing
      matches filters), most with their own call to action
- [ ] `help.html`'s content, and the `?` deep-links into it

## Cutover

- [ ] Merge `rebuild` into `master`
- [ ] Tag, deploy beta first
- [ ] Exercise beta **authenticated** — an unauthenticated `303` sweep
      proves nothing (`auth_gate` redirects before any route body, or
      its queries, ever run)
- [ ] This is the cutover, not a staged rollout — no parallel Jinja
      instance is kept running anywhere once beta is confirmed good
      (`REBUILD.md` decision 6)
- [ ] Rewrite `docs/ARCHITECTURE.md` to describe the new tree (it is
      deliberately stale until this point — see `CLAUDE.md`)
- [ ] Bump `VERSION`

---

## Standing verification checklist (applies throughout, not one phase)

Per `REBUILD.md` §7 — not a phase, a practice that applies to every step
above:

- The 60 pure-Postgres tests stay green, always.
- Each module's ported tests green in CI before moving to the next
  module.
- **Per screen:** verify against `db/seed_demo.sql`'s deterministic
  data — its figures are fixed and can be checked directly. Compare on
  `(date, description, amount)`, never on entry id (`SPEC.md` decision
  17). No standing second instance to diff against — check out
  `master` locally on demand if a specific figure ever needs a real
  cross-check (`REBUILD.md` decision 6).
- **Export parity:** byte-compare CSV and XLSX against current output.
- **Manual browser verification** for anything visual or interactive,
  per `CLAUDE.md`'s standing rule — especially hover states, live
  client-side recompute, focus management, collapse/drag.

---

## Decisions / changes log

Append-only, most recent first. Numbered `REBUILD.md` §5 decisions get a
one-line pointer here; smaller in-flight reorderings that don't rise to
that level get a line of their own.

- **2026-08-30** — Phase 4.1 complete (screen 5 of 5: Ledger),
  `frontend/src/reports/LedgerPage.tsx` plus new backend
  (`modules/reports/repository.py::ledger_accounts`/`ledger_lines`,
  `service.ledger_rows`, `GET /reports/ledger` — no export siblings,
  matching legacy). The only screen this phase needing real new backend
  work first; confirmed no itemized-per-account-lines endpoint existed
  anywhere before this. 9 new backend tests (542 total). See Current
  status for the full write-up, including the typed-client
  regeneration step every future backend-adding phase will need too.
- **2026-08-30** — Phase 4.1, screen 4 of 5: Variance done,
  `frontend/src/reports/VariancePage.tsx` — native-depth vs. rolled-up
  discriminated by `result.rolled_up`, both rendered by the same
  `useCollapsibleTree` call (an id-less rolled-up row degrades to
  "never collapsible" for free, no branch needed). Compare-to/Roll-up-to
  picker values read from the response's own resolved fields, not the
  raw URL params, since the service can auto-pick/auto-default both. See
  Current status for the full write-up, including a real (not buggy)
  blank-Compare edge case found against `seed_demo.sql`.
- **2026-08-30** — Phase 4.1, screen 3 of 5: Income Statement done,
  `frontend/src/reports/IncomeStatementPage.tsx` — rows mode and Split
  mode unified around one body-rendering path (`periodsOf`/
  `periodsTotalsOf`/`rowPeriod`/`groupPeriod` treat rows mode as a
  one-period matrix), discriminated only where the header shape and
  response structure genuinely differ. Also fixed a real,
  previously-undiscovered bug in `modules/reports/repository.py::
  budget_line_totals` (a bind-param-immediately-before-a-Postgres-`::`-
  cast parsing gap, only reachable with both `date_from`/`date_to` set,
  never covered by any test until this screen's own manual verification
  hit it live) — one new regression test, confirmed to actually fail
  pre-fix. See Current status for the full write-up.
- **2026-08-30** — Phase 4.1, screen 2 of 5: Cash Flow done,
  `frontend/src/reports/CashFlowPage.tsx`, plus the new shared
  `widgets/PeriodPresetPicker.tsx`/`periodPresets.ts` (promoted from
  Income Statement to both range reports per
  `UI_CONSISTENCY_AUDIT.md` §4b, landing with its first caller rather
  than waiting). See Current status for the full write-up.
- **2026-08-30** — Phase 4.1 started: Balance Sheet (screen 1 of 5) done,
  `frontend/src/reports/BalanceSheetPage.tsx`. First screen built since
  the Phase 3 go/no-go gate passed. Also the first phase verified with a
  real browser pass in-session (`mcp__Claude_Browser__*` tools were
  available this time) rather than deferring that check — see Current
  status for the full write-up, including an unrelated stray edit found
  in `frontend/src/format/shortcut.ts` and reverted before this commit.
- **2026-08-30** — First real-browser QA pass (David, on his own
  machine, against a real `docker compose up -d --build`) surfaced six
  genuine bugs across Phase 3.2–3.4, all fixed same-session:
  **(1)** `TrialBalancePage.tsx`'s Scenario field, and `JournalPage.tsx`'s
  Scenario/Account/Payee/Amount-operator filters, and `NewEntryPanel.tsx`'s
  Load-template/Scenario/Payee fields were still plain `<select>`s —
  legacy's own `combobox.js` progressively enhances *every* `<select>` in
  the app (`querySelectorAll("select:not([data-enhanced])")`, no
  exceptions), so all eight became real `Combobox.tsx` instances instead;
  the payee field also gained `onCreate` wired to `POST /payees/quick-
  create` (already existed server-side, unused until now), matching
  legacy's `data-create-url` on that one field specifically.
  **(2)** `NewEntryPanel.tsx`'s Date field was a plain `<input
  type="date">` instead of `DatePicker.tsx` — the one field in the
  Journal that hadn't gotten the port `TrialBalancePage.tsx`'s "As of"
  and the filter bar's From/To already had.
  **(3)** The reversal/tag badges and "Clear filters" in `JournalPage.tsx`
  were `<button>`s carrying `.badge`/`.button-link` classes — both
  classes' CSS only has rules for `a.button-link`/no button-specific
  `.badge` override at all, so a `<button>` fell through to the bare
  `button` element rule and picked up filled accent-button chrome
  neither was ever meant to have. Legacy's own markup for both is a
  real `<a>`; switched to `<Link>`, relying on `Link`'s own
  `preventDefault()` (same mechanism that already stops `<summary>`'s
  native toggle for `DescriptionCell.tsx`) rather than a redundant
  handler of our own, since a handler calling `preventDefault()` before
  `Link`'s own click logic runs would have suppressed its navigation
  outright.
  **(4)** `Combobox.tsx`'s Tab-to-commit didn't commit an arrow-key
  highlight: its `resolveAndClose()` treated "nothing typed" as "field is
  empty, clear it" without checking whether the user had actually
  arrow-key-navigated to a row first (`manualActive`) — since arrow keys
  never touch `inputText`, tabbing away after ArrowDown-ing to an option
  (never typing) silently discarded the highlighted pick. Fixed by
  gating that branch on `manualActive === null` too.
  **(5)** `format/shortcut.ts` (new) ports `option-key.js`'s Mac/iPad
  detection — `altLabel('R')` returns `⌥R` on an Apple platform, `Alt+R`
  otherwise — as a plain function called at render time instead of
  legacy's client-side text-node sweep (a React re-render already
  produces the right text from source data; no DOM walking needed).
  Wired into every `Alt+X` hint in `NewEntryPanel.tsx`/`JournalPage.tsx`.
  Combobox/scrollbar and `.badge`/tag-pill "black fill, cramped text"
  were also flagged in the same pass but turned out to be the *same*
  root cause as (1)/(3) rather than separate CSS bugs — the ported CSS
  itself (`.combobox-panel`, `.badge`) was already byte-identical to
  legacy's; only the JSX markup choosing the wrong element/component was
  wrong. Verified: a real `docker compose up -d --build`, `tsc -b`,
  `oxlint` (0 warnings), `vite build`, and an HTTP round trip exercising
  login, `GET /entries`, and the new `POST /payees/quick-create` call —
  all clean. Not re-verified in an actual browser (still no browser tool
  in this session); that pass is what surfaced these in the first place
  and needs to happen again once these fixes land.
- **2026-08-30** — Phase 3.4 done, and with it `REBUILD.md` §9's own
  go/no-go gate: **pass, proceed to Phase 4.** `frontend/src/journal/`
  (`JournalPage.tsx`, `NewEntryPanel.tsx`, `EntryGrid.tsx`/`gridLines.ts`,
  `BulkTagsDialog.tsx`, `DescriptionCell.tsx`, `MemoCell.tsx`), plus two
  new reusable widgets (`widgets/TagInput.tsx`, `widgets/
  useInlineEdit.ts`) and `widgets/useSelectMode.ts` made generic (`<T>`)
  to cover the Journal's own string entry ids. No backend changes needed
  — `modules/entries/` (Phase 1.5) and `modules/reference/`/`modules/
  scheduling/`'s reference-data routes already carried everything this
  screen needs; `widgets/usePostableAccounts.ts` re-derives legacy's
  `postable_accounts_for_pickers`/`postable_accounts_by_scenario`
  client-side from `GET /accounts`+`GET /account-levels`+`GET /scenarios`
  rather than adding a bespoke endpoint. See Current status for the full
  write-up, including the `useInlineEdit.ts` factoring decision (sharing
  what `description-edit.js`/`memo-edit.js` deliberately kept as two
  files) and a real HTTP round trip confirming `journal_lines.debit`/
  `.credit` are `NOT NULL` generated columns (always a Decimal string,
  unlike Trial Balance's own `max(int, 0)` gap).
- **2026-08-30** — Phase 3.3 done: `frontend/src/reports/TrialBalancePage.tsx`,
  the Point-in-time report archetype's first real screen. Filter state
  lives in the URL's own query string (`useSearchParams`), not component
  state — the direct equivalent of legacy's own GET-and-redisplay form
  design, keeping the page bookmarkable and its prev/next links real
  `<Link>`s. Three reusable pieces factored out: `format/money.ts`
  (`formatMoney`/`isZeroAmount`, ported from `money-format.js`'s pure
  formatting logic, deliberately not its DOM-rewrite mechanism — React
  re-renders from state, so there's no static HTML to rewrite after the
  fact), `widgets/useCollapsibleTree.ts` (report-tree.js's collapse/
  expand mechanics, generic over any account-tree row list), and `api/
  useScenarios.ts` (a plain `GET /scenarios` hook). No backend changes
  needed — `GET /reports/trial-balance` has existed since Phase 1.4/1.14.
  See Current status for the full write-up, including a real `debit_
  balance`/`credit_balance` type gap (`string | number`, not always
  `string`) found via the actual HTTP response, not assumed.
- **2026-08-30** — Phase 3.2 done: `frontend/src/tags/TagsPage.tsx`, the
  Management/CRUD archetype's first real screen, plus the client-router-
  vs-API-path decision Phase 3.1 deferred, now resolved: the SPA's own
  routes live under a new `/app/*` namespace (`main.py`'s two new
  `GET /app`/`GET /app/{path:path}` fallback routes), not an `/api`
  prefix on every data route — rejected once checked for real, since
  `analytics/router.py`'s own `/api/*` is already a real, external,
  shipped Connect BI contract that prefixing `modules/entries/`'s
  `/entries` the same way would collide with. `react-router-dom@^7`
  added; `main.tsx` now wraps the app in a real `BrowserRouter`. Two
  reusable pieces factored out of the page itself: `widgets/
  useSelectMode.ts`, `widgets/MergeDialog.tsx`. See Current status for
  the full write-up, including a stale legacy CSS comment found (and not
  trusted over the real template) and a confirmed real `oxlint`
  `react(refs)` false positive worked around by restructuring rather
  than suppressed.
- **2026-08-29** — Phase 3.1 done: `frontend/src/auth/` (`sessionContext.ts`/
  `SessionProvider.tsx`, `LoginPage.tsx`) plus two backend additions this
  phase's own frontend work surfaced the need for: `GET /me` now echoes
  `csrf_token` (previously only `id`/`username`), and a new unauthenticated
  `GET /config` (`main.py`) exposes `version`/`demo_banner`/`demo_user`/
  `demo_password` — with `demo_user`/`demo_password` deliberately omitted
  whenever `demo_banner` is false, a real security-relevant departure from
  legacy's own Jinja-globals shape (see Current status for why). `api/
  client.ts` gained an `X-CSRF-Token` request middleware and a global
  `401` handler; `api/useAppConfig.ts` and `shell/Shell.tsx`'s new
  `version` prop close the "no footer version number" gap Phase 2.4 left
  open. `App.tsx`'s placeholder `GET /healthz` check and hardcoded
  `PLACEHOLDER_USER` are both gone, replaced by a real three-way branch
  on session state. `index.css` gained four more byte-verified ranges
  (the login split-screen/demo-callout, `label.field`, `.checkline`,
  `.grid-form`). Deliberately still deferred: any client-side router —
  login has no URL of its own to reconcile with the API's existing paths,
  so the real forcing function waits for Phase 3.2. See Current status
  for the full write-up.
- **2026-08-29** — Phase 2.5 done: `frontend/src/widgets/` —
  `NumberStepper.tsx`, `ConfirmDialog.tsx`/`confirmContext.ts`,
  `DatePicker.tsx`, `Combobox.tsx`. Decision, for all four: port the
  existing vanilla-JS widget as a React component rather than adopt
  Radix/shadcn, since each one encodes a real, previously-debugged
  browser-quirk fix (the iOS `select()` no-op, Safari's default Tab-order
  gap, the roving-tabindex day grid) an off-the-shelf component wouldn't
  reproduce for free. `index.css` gained six more byte-for-byte ranges
  from `style.css` (the foundational button/input/select/textarea base
  styles plus the four widgets' own rules). See the Current status
  section for the full write-up, including the scope narrowed relative
  to each legacy original (no hidden native `<select>` in `Combobox`, no
  `data-confirm` form auto-wiring in `ConfirmDialog`) and the one real
  `oxlint` finding fixed along the way (splitting `useConfirm()` into its
  own file after `react(only-export-components)` flagged mixing a hook
  and a component together).
- **2026-08-29** — Phase 2.4 done: `frontend/src/shell/` — `Shell.tsx`/
  `Sidebar.tsx`/`Topbar.tsx`/`FlashBanner.tsx` plus their supporting
  `nav.ts`/`useSidebarPin.ts`/`useSidebarGroupCollapse.ts`, ported from
  `app/templates/base.html` and `sidebar.js`/`sidebar-collapse.js`; the
  pre-paint theme/font/pinned-sidebar restore script moved from
  `base.html`'s own inline `<head>` script into `frontend/index.html`
  directly, unchanged. `index.css` gained four more byte-for-byte ranges
  from `style.css` (top bar/sidebar/footer, flash messages, the shared
  chevron, the 720px/reduced-motion rules). See the Current status
  section for the full write-up, including why `user` stays a plain
  nullable prop with no real session behind it yet, why logout is a
  button instead of a form, and the one real `oxlint` finding fixed
  along the way (`FlashBanner`'s state derivation moved out of an effect
  and into `useState`'s own lazy initializer).
- **2026-08-29** — Phase 2.3 done: `frontend/src/index.css` — the 320 CSS
  custom properties (Slate default + 21 `data-theme` variants) and 3
  `data-font` bundles, ported byte-for-byte from `app/static/style.css`'s
  first 565 lines (confirmed, not assumed, that every one of the source
  file's 320 custom-property declarations sits inside that range). See
  the Current status section for the full write-up, including why the
  Vite scaffold's own `color-scheme: light dark` reset was dropped and
  how this session verified it for real without Docker or a pre-installed
  Node (a portable Node binary plus an already-running `backend-db-1`
  Postgres container from an earlier session).
- **2026-08-30** — Phase 2.2 done: a typed API client — `backend/scripts/
  dump_openapi_schema.py` (new, needs no DB/Docker) feeds
  `openapi-typescript` to generate `frontend/src/api/schema.ts`
  (committed, not gitignored — the Docker frontend-build stage has no
  Python to regenerate it), wrapped by `frontend/src/api/client.ts`'s
  `openapi-fetch` client. `App.tsx`'s `/healthz` check now goes through
  it instead of a bare `fetch`. See the Current status section for the
  full write-up, including why response bodies mostly type as `unknown`
  (Phase 1's own "responses stay plain dicts" decision, not a gap this
  phase introduces) and why CSRF-header attachment is deliberately not
  wired in yet (no session state exists to read a token from until
  Phase 3's login screen).
- **2026-08-30** — Phase 2.1 in progress: `frontend/` scaffolded (Vite +
  React + TypeScript), wired into `main.py` via a new `postwarden_
  static_dir` setting and a `StaticFiles` mount registered last (after
  every module router) and only when the directory exists. `backend/
  Dockerfile` is now a two-stage build (a discarded `node:22-slim`
  builder) and `backend/docker-compose.yml`'s build context moved to the
  repo root to reach it. See the Current status section for the full
  write-up, including a real, open gap (SPA deep-link/refresh support,
  deferred to whichever phase wires in a client-side router) and the one
  thing this session could not finish: a real `docker compose up -d
  --build`, blocked by this sandbox's Docker daemon failing to pull
  `node:22-slim` (reproducible `DeadlineExceeded`, unrelated to the
  changes themselves — see Open questions).
- **2026-08-30** — Phase 1.15 done, and Phase 1 as a whole: the gate —
  see the Current status section above for the full write-up. No module
  code changed; this phase pushed `rebuild` to `origin` for the first
  time (19 unpushed commits, Phase 1.5 through 1.14), which surfaced
  that CI had never actually run for any of this work and that the 60
  pure-Postgres tests had zero CI coverage on any branch. Fixed the
  latter with a second `backend-ci.yml` job (`invariants`, its own
  Postgres service); both jobs went green on the first real run (60
  passed, 523 passed). Next: Phase 2, the frontend.
- **2026-08-29** — Phase 1.12 done: `export/` — see the Current status
  section above for the full write-up (the shared CSV/XLSX writer
  package, plus new export routes on `modules/reports/`/`modules/
  entries/`). `export/` itself ended up scoped to two files of pure
  writer plumbing rather than every report's own export logic — each
  consuming module owns its own `export.py`, the same vertical-slice
  boundary every module already draws for `service.py`/`repository.py`.

- **2026-08-29** — Phase 1.11 done: `modules/auth/` — see the Current
  status section above for the full write-up (login/logout/session/
  CSRF mechanism plus account settings, deliberately scoped to *not*
  retrofit entries/staging/imports/budget/reference/scheduling to use
  it — deferred to Phase 1.14 per the `modules/budget`-on-`reference`
  precedent — `deps.py` being the one module meant to be imported
  directly rather than forked, `RateLimitedError`/`InvalidCredentialsError`
  giving `login` real 429/401 status codes, and the CSRF token moving
  from a hidden form field to an `X-CSRF-Token` header).
- **2026-08-29** — Phase 1.10 done: `modules/scheduling/` — see the
  Current status section above for the full write-up (`materialize_due_
  schedules` ported and tested but deliberately not wired into anything
  until `modules/auth/` exists, a `SAVEPOINT`-per-schedule fork of
  `check_deferred_constraints` for the same reason `reverse_entries_
  bulk` needed one, the manual balance check staying real app logic here
  unlike `modules/entries/`'s, `toggle_schedule`/`delete_template`
  harmonized to check-and-raise the same way five `modules/reference/`
  routes already were, and `domain/periods.py` gaining `advance_date`).
- **2026-08-29** — Phase 1.9 done: `modules/reference/` — see the Current
  status section above for the full write-up (five legacy top-level
  resources in one module rather than five near-empty ones, five write
  routes harmonized to check-and-raise on an unknown id matching their
  already-checked siblings, `merge_payees`/`merge_tags` now validating
  the survivor id up front instead of surfacing a raw `ForeignKeyViolation`
  the way legacy's own version could, `_accounts_with_gaps`/
  `top_level_types_taken`/`TYPE_LABELS` left as frontend concerns, and a
  shared `_bad_request` router helper since every write route here needs
  the identical `(ValueError, SQLAlchemyError)` -> 400 mapping).
- **2026-08-29** — Phase 1.8 done: `modules/imports/` — see the Current
  status section above for the full write-up (forking `entries`/
  `staging`'s account-lookup and constraint-check helpers, resolving
  every account code up front instead of relying on a `NOT NULL`
  violation the way legacy's own insert does, an `id DESC` tiebreaker fix
  in `recent_batches` caught by a same-transaction test, `Decimal`
  throughout both parsers, the mapped importer's JSON-shaped preview/
  commit round-trip replacing legacy's hidden-form-fields-plus-base64
  shape, and no `GET /import/mapped` route since that page has no data of
  its own to serve outside `modules/reference/`).
- **2026-08-29** — Phase 1.7 done: `modules/budget/` — see the Current
  status section above for the full write-up (the guard trigger firing
  immediately rather than deferred, forking `reports.repository`'s
  account/scenario queries, reusing `domain.accounts.flatten_tree(...,
  zeros=True)` instead of a second near-duplicate flatten, and no
  server-side default-scenario selection since `modules/reference/`
  doesn't exist yet).
- **2026-08-29** — Phase 1.4 done: `modules/reports/`. Ported from
  `app/main.py`'s report-building functions with comments/docstrings
  kept close to verbatim, per REBUILD.md §6's own instruction for this
  phase specifically. A few implementation decisions worth recording:

  1. **`income_statement_groups` went to `domain/accounts.py`, not
     `service.py`**, even though REBUILD_STATUS.md's own Phase 1.4
     checklist only names it implicitly (it's `income_statement_rows`'
     dependency, not separately called out as one of the "hard"
     functions). It's pure — no DB, no framework import — the same
     category as `build_account_tree`/`flatten_tree` right next to it,
     and its own `signed()` helper turned out to be *exactly* the
     duplicate `normalize_zero`'s Phase 1.1 docstring already called out
     as unfixed ("legacy code duplicated this exact guard in two places
     ... with no shared helper") — `accounts.py` had been quietly
     importing `normalize_zero` unused since 1.1, waiting for this.
     `scale_income_statement_result` is *also* pure (plain dict
     arithmetic, no DB) but stayed in `service.py` next to
     `income_statement_matrix`, the one function that calls it —
     REBUILD_STATUS.md's own Phase 1.4 list names the two together, and
     splitting a function from its one caller across two modules for a
     purity technicality would cost more than it buys.
  2. **No `schemas.py`** in this module, unlike `modules/entries/`
     (REBUILD.md decision 3's own named example). Every route here is a
     GET with plain query params FastAPI already validates from the
     function signature — no request body, so no Pydantic model earns
     its keep. Response bodies stay plain dicts, same shape `domain/`'s
     own functions already return; `json.py`'s `configure_decimal_
     encoding()` (Phase 1.3) is what makes a bare dict return serialize
     correctly with zero extra work here, confirmed rather than assumed
     (`test_router.py` checks a `Decimal` total renders as `"3000.00"`,
     a string, over a real `TestClient` request).
  3. **Router built, not mounted.** `router.py` exists as a standalone
     `APIRouter`, fully tested via a throwaway `FastAPI()` +
     `include_router()` (same pattern `test_json.py` established), but
     `main.py` doesn't import it — real mounting is still Phase 1.14,
     once every module in `modules/` has built one; `main.py`'s own
     docstring already said as much before this phase started.
  4. **A report route doesn't embed `scenarios`/`account_levels` picker
     lists**, unlike the legacy Jinja routes (which always passed
     `scenarios_all()`/`account_levels_all()` into the template
     alongside the report data). Those queries belong to
     `modules/reference/` (Phase 1.9), which doesn't exist yet — reaching
     into it now would break the "deletable on its own" test REBUILD.md
     decision 3 sets for a vertical slice. The frontend will fetch those
     separately once that module exists.
  5. **`backend/tests/conftest.py`, new** — the first DB-backed tests in
     `backend/`. Mirrors the root `tests/conftest.py`'s own scratch-
     database pattern (`DROP`/`CREATE DATABASE`, load `db/schema.sql`),
     one level in: a disposable `postwarden_backend_test` database on
     whatever Postgres server `DATABASE_URL` already points at (so it
     works unmodified against both `backend-ci.yml`'s bare service
     container and a local `docker compose up -d db`, which loads the
     *main* `postwarden` database with seed data this file never
     touches). Deliberately **schema-only, no `seed.sql`**, unlike the
     root conftest — every test here builds its own minimal fixture rows
     (`mk_account`/`mk_scenario`/`mk_entry`/`mk_line`), so there's no
     risk of a test's own account code colliding with `seed.sql`'s real
     chart of accounts. The `conn` fixture never commits (rolled back
     per test), which also means the genuinely `DEFERRABLE INITIALLY
     DEFERRED` triggers (balance/entry-has-lines, SPEC.md decision 2)
     never fire in these tests — fine, since these tests exercise report
     *reads* against fixtures already known to be correct, not those
     invariants (`tests/test_invariants.py`'s job, unchanged, at the
     repo root).

  28 new tests (5 pure `domain/accounts.py` tests for
  `income_statement_groups`, no DB; 9 direct `repository.py` tests; 9
  DB-backed `service.py` tests including both of `compute_variance`'s
  paths; 6 end-to-end `router.py` tests via `TestClient`) — 93 passed
  total. Verified for real: a full `docker compose up -d --build` (clean
  log, `/healthz` 200), then separately, since this phase is the first
  to touch a database in `backend/`'s test suite, the exact CI shape by
  hand — a bare `postgres:16` container with no init scripts, `alembic
  upgrade head`, `pytest` — to confirm `backend-ci.yml` will actually
  pass before pushing, not just that a locally-seeded database happens
  to work.
- **2026-08-29** — Phase 1.3 done: `json.py`, closing the `REBUILD.md`
  §6 "documented gap" — a route's `Decimal`/`date` values, fixed once
  centrally instead of per-route (legacy's own fix, `str()`-ing
  debit/credit before building a JSON blob, is duplicated in
  `staging_duplicates_page`'s `groups_json` and `templates_full()`).
  Turned out to be two genuinely different bugs, not one, discovered by
  actually testing both rather than assuming a single fix would cover
  both: (1) a route that just `return`s a dict/Pydantic model goes
  through FastAPI's own `jsonable_encoder`, whose built-in `Decimal`
  handling silently downgrades to `float` — reintroducing on the way
  *out* exactly the precision-loss risk `domain/money.py`'s Phase-1.1
  switch to `Decimal` closed on the way in (confirmed with a real
  example: `jsonable_encoder({"amount": Decimal("19.99")})` returns
  `19.99` as a `float`, not the string a `NUMERIC(18,2)` value should
  round-trip as). `date`/`datetime` needed no fix on this path —
  verified, not assumed (`jsonable_encoder` already isoformats them
  correctly). Fixed via `configure_decimal_encoding()`, which registers
  a `str` encoder in FastAPI's own `ENCODERS_BY_TYPE` registry — a
  supported extension point, not a private hack, since `jsonable_
  encoder` looks up `type(obj)` there directly. (2) A route that
  explicitly builds `JSONResponse({...})` — legacy's own idiom for the
  `{"ok": True/False, ...}` action-toast responses scattered throughout
  `app/main.py`, which the ported modules keep rather than inventing a
  new shape — never goes through `jsonable_encoder` at all (it's a
  FastAPI-only helper that never runs on an already-constructed
  `Response`); Starlette's own `JSONResponse.render()` calls plain
  `json.dumps`, which raises `TypeError` outright on a bare `Decimal`
  *or* a bare `date`/`datetime`, no fallback. Fixed with a same-name,
  same-constructor `JSONResponse` in `json.py` whose `render()` supplies
  a `default=` callback handling both — a ported route only has to
  change its import (`from postwarden.json import JSONResponse` instead
  of `from fastapi.responses import JSONResponse`), nothing else at the
  call site. Wired into `main.py`: `configure_decimal_encoding()` runs
  at import time (process-wide, once, idempotent), and `app`'s
  `default_response_class` is now the new `JSONResponse`. 9 new unit
  tests under `backend/tests/test_json.py` — the two bugs above verified
  directly, plus two end-to-end `TestClient` requests (one implicit
  dict-return, one explicit `JSONResponse`) proving both paths actually
  produce `"19.99"`, not `19.99`, over real HTTP. `pytest` — 65 passed
  (56 prior + 9 new). Also verified with a real `docker compose up -d
  --build`: clean startup log (no tracebacks), `/healthz` still 200 —
  torn down after (`down -v`), not left running.
- **2026-08-29** — Phase 1.2 done: `config.py` — a `pydantic-settings`
  `Settings` class + cached `get_settings()` centralizing the six env
  vars the legacy app read ad hoc across three files (`app/db.py`'s
  `DATABASE_URL`; `app/auth.py`'s `POSTWARDEN_COOKIE_SECURE`;
  `app/main.py`'s `POSTWARDEN_ADMIN_USER`/`POSTWARDEN_ADMIN_PASSWORD`/
  `POSTWARDEN_DEMO_MODE`/`POSTWARDEN_BI_PORT`). `db.py` — a lazily-built,
  `lru_cache`d SQLAlchemy Core `Engine` plus a `get_connection()`
  generator FastAPI dependency yielding one `Connection` per request
  inside one transaction (commit on clean return, rollback on
  exception) — mirrors legacy `app/db.py`'s `tx()` contextmanager,
  including the reliance on Postgres's *deferred* constraint triggers
  firing at COMMIT rather than at the individual INSERT (SPEC.md
  decision 2). `database_url`'s default already carries the
  SQLAlchemy-flavored `postgresql+psycopg://` scheme rather than
  legacy's plain `postgresql://` — not a new decision, just matching
  the convention Phase 0.4's `alembic/env.py` and Phase 0.6's
  `backend/docker-compose.yml` already established, so `db.py` passes
  `database_url` straight to `create_engine` with no second rewrite.
  One real behavior fix caught by the test suite itself: pydantic's
  default bool coercion rejects `""` outright and is looser than
  legacy's truthy set (also accepts `"on"`/`"off"`/`"t"`/`"f"`), so
  `POSTWARDEN_COOKIE_SECURE`/`POSTWARDEN_DEMO_MODE` get a `field_validator`
  that reproduces legacy's exact `.lower() in ("1", "true", "yes")`
  check — otherwise a blank-but-set env var (a common shape in `.env`
  files) would be a startup crash instead of the harmless no-op it was
  before. The engine is built lazily on first call rather than at
  import time like legacy's pool, specifically so `DATABASE_URL` only
  has to be set before first use (e.g. in a pytest fixture) rather than
  before pytest collection, the way `tests/conftest.py`'s comment says
  legacy requires. 7 new unit tests under `backend/tests/` (all
  no-database — `create_engine` doesn't open a connection until
  something queries through it), plus a one-off manual check outside
  the suite: `docker compose up -d db`, then a real `get_connection()` →
  `SELECT 1` round trip against it, confirming the engine and
  transaction wiring actually work against Postgres and not just that
  they construct — torn down afterward (`docker compose down -v`), not
  left running. `pytest` — 56 passed (49 prior + 7 new), nothing else
  touched. `main.py` still doesn't import either module: no route needs
  the database yet, so wiring it in stays deferred to whichever module
  first needs it (reports, 1.4, is next).
- **2026-08-29** — Phase 1.1 done: `domain/money.py` (variance/percentage
  math), `periods.py` (date-shift and calendar-split helpers),
  `accounts.py` (tree rollup/flatten, P&L-net sign correction),
  `entry.py` (journal-line parsing, tag-name validation) — ported from
  `app/main.py`'s module-level `_`-prefixed helpers (`_pct_variance`,
  `_build_account_tree`, `_flatten_tree`, `_parse_lines`, etc.),
  docstrings kept close to verbatim per the "read it, don't rewrite it"
  guidance in `REBUILD.md` §4. Two deliberate deviations from a pure
  rename, both recorded in the modules' own docstrings: (1) money
  amounts are `Decimal` throughout, not the legacy `float(d)`/`float(c)`
  in `_parse_lines` — `db/schema.sql` already stores every amount as
  `NUMERIC`, which psycopg hands back as `Decimal`, so `float` was only
  ever a latent-imprecision risk introduced by one conversion on user
  input, with no upside; (2) `entry.parse_lines` takes four plain
  parallel lists instead of a Starlette `FormData` object, so the
  domain layer stays free of any FastAPI/Starlette import — the router
  (module 1.5) will call `form.getlist(...)` itself and pass the lists
  in. 48 new unit tests under `backend/tests/domain/`, exercising the
  behavior each docstring documents (day-clamping across month/year
  boundaries, split-period clipping and the `partial` flag, tree
  rollup and the zero-hide-unless-both-sides-zero rule, every
  `parse_lines`/`parse_tags` validation branch) — new tests, not a
  port, since these were file-private helpers with no direct test
  coverage of their own before (only indirect, through route-level HTML
  assertions). Verified for real: `pip install -e ".[dev]"` +
  `pytest` — 49 passed (48 new + the Phase 0 health smoke test),
  nothing else touched.
- **2026-08-29** — Phase 0.6 done, closing out Phase 0: `backend/
  docker-compose.yml` + `backend/Dockerfile`, self-contained (its own
  `db` service, its own named volume, default ports 5433/8001 so it can
  in principle run alongside a `master` checkout on 5432/8000 without a
  clash — the one case decision 6 keeps open, checking out `master`
  locally to cross-check a figure). The `backend` service's entrypoint
  runs `alembic stamp head`, not `upgrade head`: the `db` service's
  `docker-entrypoint-initdb.d` scripts already load `schema.sql` +
  `seed.sql` + `seed_demo.sql` directly on first boot, so the freshly
  -initialized database *is* the baseline already — stamping just
  records that, matching decision 5's "existing installs get `alembic
  stamp head`" language. Verified for real: `down -v` then
  `up -d --build` from scratch, clean logs, `/healthz` responds,
  `alembic_version` correctly holds the baseline revision, and
  `seed_demo.sql`'s entries are present (29 rows in `journal_entries`).
- **2026-08-29** — Phase 0.5 done: `.github/workflows/backend-ci.yml` —
  `pytest` against a Postgres 16 service container, scoped to
  `backend/**`/`db/schema.sql` paths. Steps: install `backend/` editable,
  `alembic upgrade head`, `pytest`. Verified locally by running the same
  three steps by hand against a throwaway container on 5432 before
  committing the workflow file itself.
- **2026-08-29** — Phase 0.4 done: `alembic init` under `backend/`;
  `env.py` reads `DATABASE_URL` (same env var as legacy `app/db.py`, but
  the SQLAlchemy-flavored `postgresql+psycopg://` scheme, not legacy's
  plain `postgresql://`). The baseline revision applies `db/schema.sql`
  verbatim via the raw DBAPI cursor inside `autocommit_block()` — not
  `op.execute(text(...))`, which chokes on literal `%` in the file before
  it reaches Postgres, and not nested inside Alembic's own transaction,
  which would let the file's own `COMMIT` close that transaction out from
  under it. Verified for real: `alembic upgrade head` against a fresh
  Postgres 16 container, `pg_dump --schema-only` diffed against a second
  fresh container loaded with `psql -f schema.sql` directly — identical
  except for Alembic's own `alembic_version` bookkeeping table.
- **2026-08-29** — Phase 0.1–0.3 done: `backend/` scaffolded as a
  `src`-layout package (`backend/src/postwarden/`, empty sub-packages per
  module, `main.py`/`config.py`/`db.py` stubs), dependencies pinned in
  `backend/pyproject.toml`, and open question 0.3 resolved — separate
  dependency files, not shared. Verified with a real install: `pip
  install -e ".[dev]"` + `pytest` inside `backend/` passes (one smoke
  test, `backend/tests/test_health.py`, hitting `/healthz`).
- **2026-08-29** — Decision 6 in `REBUILD.md` reversed: no second live
  instance of `master`'s app is maintained anywhere, locally or in
  prod, for comparison purposes. This is a committed, all-in rebuild —
  `master` is a git-level fallback only. Updated `REBUILD.md` (§5.6,
  §7, §8, §9), `CLAUDE.md`'s working conventions, and this file's
  Phase 0.6 / verification checklist / cutover section accordingly.
- **2026-08-29** — File created. Phase 0 not yet started.

## Open questions

Carried forward until answered; move to the log once resolved.

- **Phase 2.1's `docker compose up -d --build` verification is still
  outstanding, and Phase 2.2 adds to the same gap rather than opening a
  new one.** Everything short of the actual Docker build was verified for
  real both sessions (see Current status); the build itself couldn't
  complete because this sandbox's Docker daemon can't pull `node:22-slim`
  (or even `hello-world`) — reproducible `DeadlineExceeded` on the
  image-metadata fetch, while already-cached images (`python:3.12-slim`,
  `postgres:16`) resolve instantly. Reads as a sandbox-specific
  registry restriction, not a real problem with `backend/Dockerfile` or
  `backend/docker-compose.yml`, since this exact command is this
  project's own established working local-dev loop on this machine
  outside the sandbox. Phase 2.2 adds two new npm dependencies
  (`openapi-fetch`, `openapi-typescript`) the frontend-build stage's own
  `npm ci` would need to fetch — untested either way, since that stage
  couldn't be reached at all this session, but not a materially different
  risk than what was already unverified. **Needs**: run `cd backend &&
  docker compose down -v && docker compose up -d --build` for real
  (outside this session, or once registry access is available), confirm a
  clean build log, `GET /` serves the built SPA, `/healthz` still 200,
  and the existing authenticated-flow spot-check (login -> a protected
  route -> a CSRF-protected write) from Phase 1.14's own write-up still
  holds. Close this out (move to the log) once that run happens, before
  treating Phase 2.1 as fully done rather than in-progress — Phase 2.2
  itself is marked `[x]` regardless, since nothing about the typed client
  specifically depends on Docker (see its own "Verified for real"
  paragraph). **Confirmed still true in a later session** (the one that
  did Phase 2.3): `docker pull hello-world` — the smallest image that
  exists, already known-cached nowhere — was tried again from scratch and
  still hangs/times out the same way, so this reads as a standing
  characteristic of the sandbox rather than a one-off. That same session
  did find a real, already-running `backend-db-1` (`postgres:16`)
  container left over from an earlier one, which is what let Phase 2.3's
  own verification reach a real `uvicorn` + real Postgres + real HTTP
  check without Docker — worth trying first (`docker ps -a`) before
  assuming a from-scratch container is the only way to verify anything
  that needs Postgres.
- **A second, narrower gap surfaced doing Phase 2.3, worth tracking
  alongside the Docker one since both close on the same kind of real run:
  no browser tool exists in this session (or, per the pattern above,
  reliably in this sandbox at all).** `npm`/`node` weren't even on `PATH`
  at the start of that session either — worked around with a portable
  Node 22 binary downloaded directly (network access itself is fine, only
  the Docker daemon's own registry pulls are restricted) — but even with
  a real `npm run build` and a real `uvicorn` serving the result, there is
  no way in this environment to actually paint a page and look at it.
  Phase 2.3's own CSS port was verified as thoroughly as byte-level/
  HTTP-level checks allow (see its Current status write-up) but a real
  "cycle through the 21 themes and confirm they read correctly" pass is
  still owed, and every visual phase from here on (2.4's shell onward)
  will carry the same gap until a browser tool is available in-session.
  **Needs**: whatever machine/session eventually runs the outstanding
  `docker compose up -d --build` above should also do a real browser pass
  over at least a few themes (Ledger, Midnight, Contrast, Matrix — the
  widest spread of light/dark/accessibility/novelty) before any Phase 2.3
  or later visual work is treated as fully closed out, not just
  mechanically correct. **Confirmed still true doing Phase 2.4**, and its
  scope grew with that phase: beyond "do the themes look right," 2.4 adds
  real pointer/keyboard interaction that has never been exercised at all
  in this environment — hover-preview open/close (including the 200ms
  close grace and the hover-gap crossing it exists for), click-to-pin
  persisting and pushing the page over, per-group collapse persisting
  independently across the three sidebar groups, Escape closing an
  unpinned preview, and the ≤720px breakpoint's overlay-instead-of-push
  behavior. Every one of these was ported from a working, tested vanilla-
  JS original and re-verified only at the source-diff/bundle-content
  level this session (see Phase 2.4's own "Verified for real" paragraph)
  — real before any of it is treated as behaviorally, not just
  structurally, correct.
  **Confirmed still true doing Phase 2.5**, scope grown again: the four
  widgets add the densest keyboard/pointer surface built so far and none
  of it has been exercised by a real browser — typing into the Combobox
  and watching the panel filter and the active row track it, the iOS-
  workaround focus/select() branch, opening the DatePicker and arrow-
  key/PageUp/PageDown/Home/End-ing around the grid, the roving-tabindex
  handoff across a month change, the ConfirmDialog's Tab/Shift+Tab focus
  trap and Escape/backdrop-click cancel, and the NumberStepper's chevron-
  disable-at-bounds. `App.tsx`'s temporary `WidgetPreview` section (see
  Phase 2.5's own write-up) exists specifically so this pass has
  something real to exercise once a browser tool is available, rather
  than needing a Phase 3 screen to exist first.
  **Confirmed still true doing Phase 3.1**, scope grown once more: the
  login screen adds a real, if smaller, surface of its own — autofocus
  landing in the username field on load, tabbing username -> password ->
  Remember me -> Log in in the right order, submitting via Enter (not
  just a button click), the demo callout's `order: -1` reflow to above
  the form at the 720px breakpoint, and the once-only demo-credential
  seed effect (`LoginPage.tsx`'s `seededDemo` ref) actually behaving as
  intended — filling the fields once, then staying out of the way even
  if a user clears them by hand afterward. Every real HTTP/session-state
  transition behind these (a wrong password 401ing with the right
  message, a correct one setting a real cookie, `/me` surviving a
  refresh, logout clearing it) was verified for real over HTTP this
  phase (see Current status) — what's still unexercised is purely the
  DOM-level interaction layered on top of it.
  **Confirmed still true doing Phase 3.2**, scope grown again, and for
  the first time including real client-side navigation, not just a
  single screen's own widgets: clicking the Dashboard/Tags sidebar links
  and the topbar wordmark and actually observing a client-side
  transition (no full page reload, `current` highlighting the right
  link) rather than just trusting `react-router-dom` to do what its own
  API promises; a hard refresh at `/app/tags` actually reaching the SPA
  instead of a blank screen; the tag row's inline-edit focus+select-all-
  text on Edit and revert-on-Escape; Select mode actually revealing the
  checkbox column and the "select all" checkbox's indeterminate dash
  rendering (browser-default styling with `appearance: none` stripped —
  never explicitly styled, in legacy either, so confirming it still
  renders as *something* legible matters); the Merge dialog's own
  focus-on-open/select-all-text, Escape-to-cancel, and backdrop-click-
  to-cancel, deliberately with no Tab trap (a real, ported-as-is legacy
  gap — see Current status). Every real HTTP/data transition behind
  these (create/rename/toggle/merge/delete all actually mutating the
  `tags` table correctly, a bad id or a missing CSRF token both 400ing)
  was verified for real over HTTP this phase (see Current status) — same
  split as every phase before it: the network/data layer is real and
  checked, the DOM-level interaction on top of it isn't yet.
  **Confirmed still true doing Phase 3.3**, scope grown again: the
  account-tree collapse/expand click (and its `localStorage`-persisted
  state actually surviving a reload), the DatePicker popup opened from a
  second real page instead of just login's own, hover states on
  `.quiet-link`/the sticky header-and-two-columns behavior scrolling a
  long report, and the prev/next-month `<Link>`s actually navigating
  without a full page reload. Every real HTTP/data transition behind
  these (the report for a real scenario, `zeros`/`raw` toggled together,
  a nonexistent scenario code, both export routes) was verified for real
  over HTTP this phase (see Current status) — same split as every phase
  before it.
  **Confirmed still true doing Phase 3.4**, scope grown by more than any
  prior phase — the Journal is the densest interactive surface in the
  app: the entry grid's full keyboard flow (Tab through account -> debit
  -> credit -> memo, Enter/Shift+Enter moving vertically instead of
  submitting, the debit/credit exclusivity on typing), Distribute's
  first-row special case and its focus handoff, Add line/Clear's own
  focus management, every Alt+N/D/E/S/C/R shortcut actually firing (and
  *not* firing while a plain click, not Option+key, produces the same
  letter on a non-Mac keyboard), the tag chip input's arrow-key nav and
  Backspace-pops-last-chip behavior in both the New entry form and the
  filter bar, each entry's own `<details>` expand/collapse, and the
  description/memo cells' click-to-edit — including the 600ms debounce
  actually firing and Escape's corrective re-POST actually landing, the
  one piece of this phase with no cheap way to verify short of watching
  it happen in a real browser over real time. Every real HTTP/data
  transition behind all of this (posting a balanced entry, reversing one
  singly and in bulk with per-entry error collection, editing a
  description/memo/tag set, both exports reflecting the edit) was
  verified for real over HTTP this phase (see Current status) — same
  split as every phase before it, just with more surface than ever on
  the unverified side of it.
  **Partially closed 2026-08-30**: David did a real hands-on pass against
  a real `docker compose up -d --build` (see the decisions log's own
  entry for that date) — the first actual browser click-through any of
  Phase 3 has had. It found six real bugs (all fixed same-session: eight
  plain `<select>`s that should have been `Combobox.tsx`, a plain
  `<input type="date">` that should have been `DatePicker.tsx`, `<button>`s
  wrongly wearing `.badge`/`.button-link` classes meant for `<a>`, a
  Tab-to-commit bug in `Combobox.tsx` itself, and no Mac/iPad Option-key
  label at all) and confirmed the rest of what it touched — login, Trial
  Balance, and a first pass over the Journal's own keyboard flow
  (Distribute, Add line, Post, Select mode, Reverse) — genuinely works,
  "visually ~95% there." Distribute/Add line/Post/Select/Reverse are now
  confirmed working keyboard-and-click, for real, not just by source
  inspection. Still not exercised even by this pass: the tag chip
  input's arrow-key nav, `<details>` expand/collapse, the description/
  memo click-to-edit debounce, and whether the six fixes above actually
  look/behave right now (this fix round shipped with only the HTTP/
  build-level verification `Combobox.tsx`'s own docstring describes, not
  a second browser pass) — genuinely close this gap once David's next
  look confirms them.
