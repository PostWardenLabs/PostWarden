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

**Next step:** 1.15 — the gate: confirm the 60 pure-Postgres tests still
pass unchanged and every ported module's own tests are green in CI,
before any frontend work starts.

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
- [ ] **1.15** **Gate:** the 60 pure-Postgres tests
      (`tests/test_invariants.py`, `tests/test_cashflow.py`) pass
      unchanged, and every ported module's own tests are green in CI.
      Frontend work does not start before this.

## Phase 2 — Frontend foundations

- [ ] **2.1** Vite + React + TypeScript scaffold under `frontend/`,
      built output served by FastAPI `StaticFiles`. Confirm no Node
      process is required at runtime.
- [ ] **2.2** Typed API client generated from the backend's OpenAPI
      schema.
- [ ] **2.3** Port the 327 CSS custom properties and 21 themes from
      `app/static/style.css`, essentially verbatim.
- [ ] **2.4** Shell: sidebar (hover-preview + click-to-pin, three
      collapsible groups), topbar, flash banners, and the pre-paint
      theme/font restore script that currently prevents FOUC via an
      inline `<head>` script.
- [ ] **2.5** Per-widget decision, recorded here as it's made — Radix/
      shadcn vs. porting the existing JS — for combobox, datepicker,
      confirm dialog, number-stepper. Each existing widget encodes a
      real fix (`e.code` for Option-remapped keys, explicit `tabIndex`
      for Safari, the iOS `select()` no-op) that an off-the-shelf
      component won't reproduce for free.

## Phase 3 — One screen per archetype (the go/no-go gate)

Ascending risk, per `REBUILD.md` §6:

- [ ] **3.1** login — proves the pipeline end to end
- [ ] **3.2** tags — Management/CRUD archetype
- [ ] **3.3** trial balance — Point-in-time report archetype
- [ ] **3.4** Journal — the hardest screen in the app

**Gate:** if Journal does not come out clearly better than the Jinja
version, stop and reconsider per `REBUILD.md` §9. Record the outcome of
this gate here, whichever way it goes, before Phase 4 starts.

## Phase 4 — Fill in by archetype

Largely configuration once the Phase 3 archetype components exist.

- [ ] **4.1** Remaining Range/period + Point-in-time reports:
      income_statement, cash_flow, balance_sheet, variance, ledger
- [ ] **4.2** Remaining Management/CRUD: payees, scenarios,
      account_levels, scheduled, entry_templates, settings
- [ ] **4.3** staging (Filterable transaction list, second instance)
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

None currently open.
