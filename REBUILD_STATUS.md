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

**Phase 0, not yet started.** `REBUILD.md` and `CLAUDE.md` (refitted for
this branch) are the only things that exist on `rebuild` so far — no
`backend/`, no `frontend/`, no CI workflow. `master` is untouched and
still what's deployed.

**Next step:** 0.1 — scaffold the `backend/` tree.

---

## Phase 0 — Scaffolding

Not one of `REBUILD.md` §6's five numbered phases, but has to happen
before any of Phase 1's code does. Pure setup, no product logic.

- [ ] **0.1** Create the `backend/src/postwarden/` tree per `REBUILD.md`
      §6 (`domain/`, `modules/`, `export/`, `analytics/`, `main.py`,
      `config.py`, `db.py`) — empty packages first, so the directory
      shape is settled before anything fills it in.
- [ ] **0.2** Pick and pin backend dependencies (FastAPI, SQLAlchemy
      Core, Alembic, Pydantic v2, pytest, psycopg driver, uvicorn) —
      record versions in `backend/`'s own dependency file.
- [ ] **0.3** Decide: one shared Python dependency file for legacy
      `app/` + new `backend/`, or fully separate. They'll run as two
      containers side by side for a while (decision 6), which argues
      for separate; but duplicated pins drift. Decide once, record the
      reasoning here.
- [ ] **0.4** `alembic init`, baseline revision generated from the
      current `db/schema.sql` (`REBUILD.md` decision 5). Confirm
      `alembic upgrade head` against a fresh database reproduces
      `schema.sql` with no diff.
- [ ] **0.5** GitHub Actions CI workflow: `pytest` against a Postgres
      service container. The repo has no CI today — this is new, not a
      port. Lands empty-green (no modules yet) so every subsequent PR is
      checked from the start.
- [ ] **0.6** `docker-compose` service for the new backend's own
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

- [ ] **1.1** `domain/money.py`, `periods.py`, `accounts.py`, `entry.py`
      — pure logic, zero framework/IO imports. Unit tests only, no DB,
      no FastAPI.
- [ ] **1.2** `config.py` + `db.py` — settings and the SQLAlchemy Core
      engine/session setup.
- [ ] **1.3** Central `Decimal`/`date` JSON encoder, fixed once here
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

- **2026-08-29** — Decision 6 in `REBUILD.md` reversed: no second live
  instance of `master`'s app is maintained anywhere, locally or in
  prod, for comparison purposes. This is a committed, all-in rebuild —
  `master` is a git-level fallback only. Updated `REBUILD.md` (§5.6,
  §7, §8, §9), `CLAUDE.md`'s working conventions, and this file's
  Phase 0.6 / verification checklist / cutover section accordingly.
- **2026-08-29** — File created. Phase 0 not yet started.

## Open questions

Carried forward until answered; move to the log once resolved.

- 0.3: shared vs. separate dependency files between `app/` (legacy) and
  `backend/` (new).
