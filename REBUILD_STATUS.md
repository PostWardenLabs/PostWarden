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

**Next step:** 1.4 — `modules/reports/`, the ~450 "genuinely hard" lines.

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
- [ ] **1.4** `modules/reports/` — the ~450 "genuinely hard" lines,
      ported **with comments and docstrings intact**:
      `_build_account_tree`/`_flatten_tree`, `_income_statement_matrix`/
      `_scale_income_statement_result`, `_cash_flow_rows`/
      `_cash_flow_tie_out`, `_compute_variance`, `_split_periods`. Keep
      calling the existing Postgres SRFs (`fn_trial_balance`,
      `fn_cash_flow_lines`, `fn_rollup_balance`, `fn_account_balances`)
      directly — **not** modeled through SQLAlchemy Core (decision in
      `REBUILD.md` §6).
- [ ] **1.5** `modules/entries/` (router · schemas · service ·
      repository · tests) — the Journal backend.
- [ ] **1.6** `modules/staging/`
- [ ] **1.7** `modules/budget/`
- [ ] **1.8** `modules/imports/` — both importers (plain CSV and the
      mapped/rules importer).
- [ ] **1.9** `modules/reference/` — accounts, payees, tags, scenarios,
      account levels (CRUD).
- [ ] **1.10** `modules/scheduling/` — scheduled entries, entry
      templates.
- [ ] **1.11** `modules/auth/`
- [ ] **1.12** `export/` — shared CSV/XLSX writers, consumed by
      `entries`, `reports`, and `imports` alike. XLSX carries live
      Excel formulas (cell-by-cell sums, not ranges) — port that
      behavior deliberately, not incidentally.
- [ ] **1.13** `analytics/` — star-schema views + the documented
      `/api/*` contract (the 5 existing routes).
- [ ] **1.14** `main.py` cut down to app factory + router mounting only.
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
