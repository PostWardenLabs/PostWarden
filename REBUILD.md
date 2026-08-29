# The rebuild — replacing the Jinja2 UI and restructuring the app layer

This is the standing plan for the `rebuild` branch. It is the counterpart
to `SPEC.md` (which explains why the *schema* is shaped the way it is)
and `UI_CONSISTENCY_AUDIT.md` (which explains why the *screens* are
shaped the way they are). Neither of those is superseded here — both are
inputs to this work, and `UI_CONSISTENCY_AUDIT.md` in particular turns
out to be the component spec for the new frontend, written a week before
anyone decided to build one.

Read this before touching anything on this branch.

---

## 1. What this branch is

`master` holds PostWarden as it shipped: FastAPI + Jinja2 + vanilla JS,
no build step, no SPA. It works, it is deployed to `beta` and `demo`,
and it stays running and untouched for the duration.

`rebuild` replaces the application layer with:

- a **React + TypeScript SPA** (Vite, plain SPA — not Next.js), and
- a **restructured FastAPI backend** — vertical-slice modules, a pure
  domain layer, SQLAlchemy Core, Alembic, Pydantic response schemas.

`db/schema.sql` is carried across **unchanged**. See §3.

This is a rebuild of the app layer, not of PostWarden. The distinction
matters and is the reason the risk profile here is unusual — see §3.

## 2. Why

The trigger is recorded in `BACKLOG.md` under "Should UI be React.js?":
interface changes are tedious, and one change that applies to several
pages requires doing the same tweak several times. That is not a
complaint about Jinja2 — it is the accurate observation that **26
templates share no component model**, so there is nowhere for a shared
change to live.

Three things compound it:

- **The heavy screens have outgrown the model.** Journal
  (`entries.html`, 346 lines) and Staging (`staging.html`, 310 lines)
  are backed by roughly 1,240 and 900 lines of hand-written DOM
  scripting respectively. Both are dense, stateful, fast-updating
  surfaces being driven by a page-reload-plus-`fetch()` model.
- **The widget layer is bespoke and duplicated.** Three separate files
  implement "inline edit" for different fields —
  `staging-inline-edit.js` (127), `description-edit.js` (129),
  `memo-edit.js` (152) — because there is no component to share. The
  same singleton entry grid in `app.js` is reused across four screens
  by mutating its DOM in place.
- **The forward backlog is all component-shaped work.** Multicurrency,
  i18n, a mobile app, AR/AP reports, charts, custom themes. Every one
  is dramatically cheaper with a component model and more expensive
  without — i18n alone means hand-editing all 26 templates. **The cost
  of this migration grows with every feature added before it.**

## 3. What does not change, and why that matters more than anything else

`db/schema.sql` (1,259 lines) holds **10 triggers, 14 functions, 4 views
and 29 CHECK constraints**. Double-entry balance is a `DEFERRABLE
INITIALLY DEFERRED` constraint trigger firing at COMMIT, with no code
path around it — not from the app, not from `psql`. Immutability,
reversal integrity, hierarchy acyclicity, scenario locks, staging
provenance rules and budget-line rules are all equally unavoidable.

**The consequence: a bug in this rebuild cannot corrupt the ledger.** It
can produce a wrong error message or a wrong-looking report, but it
cannot write books that do not balance. That is the single fact that
makes a rebuild of this scope defensible rather than reckless, and it is
a direct dividend of `SPEC.md` decision 2 ("the balance invariant lives
in a deferred constraint trigger") and decision 6 ("the reporting layer
is part of the schema").

The 60 pure-Postgres tests in `tests/test_invariants.py` and
`tests/test_cashflow.py` never import the app. **They run verbatim
against the new backend, in any language.** They are the only part of
the current suite that is independently trustworthy, and they are the
safety net.

## 4. The measured starting point

Numbers here are measured, not estimated, and are what the phase
ordering below is derived from.

### Backend — `app/main.py`

5,908 lines, of which **only 3,457 are executable**. 543 blank, 792
comments, 1,117 docstrings. That 32% is unusually high-value prose
carrying rationale and spec cross-references. **Read it; do not
rewrite it.** Much of it should migrate to the new modules verbatim.

| Bucket | Lines | What |
|---|---|---|
| Genuinely hard | ~450 | `_build_account_tree` + `_flatten_tree` (90), `_income_statement_matrix` + `_scale_income_statement_result` (~110), `_cash_flow_rows` + `_cash_flow_tie_out` (100), `_compute_variance` dual-path (109), `_split_periods` + date shifts (~70) |
| Mechanical | ~2,200 | 12 exports (812), reference CRUD (~700), staging + import (~550), filter builders (~150) |
| Effectively free | ~800 | thin wrappers over SQL functions and views, the 5 existing `/api/*` routes |

The single most important structural fact: **every report core is
already a headless `_*_rows()` function returning a plain dict**, and
each is already consumed three ways — Jinja, `csv.writer`, and openpyxl.
A structure that survives being written to a spreadsheet is not
HTML-shaped. No formatting is baked in: `money()` and `dateformat()` are
render-time Jinja filters emitting `data-value` attributes that
client-side JS rewrites per user preference. Numbers stay numeric all
the way through the backend.

That is the thing that usually kills this kind of migration, and it is
already clean here.

### Frontend — 26 screens, but the shell is the biggest line item

| Complexity | Count | Screens |
|---|---|---|
| **Heavy** | 6 | entries, staging, income_statement, budget, staging_duplicates, accounts |
| **Moderate** | 14 | tags, payees, scheduled, entry_templates, trial_balance, balance_sheet, variance, cash_flow, ledger, settings, scenarios, account_levels, import_mapped_review, dashboard |
| **Trivial** | 6 | import, import_mapped, connect_bi, account, login, help |

Plus `base.html` and **~1,350 lines of JS that loads on every page**.
`combobox.js` (300) replaces *every* `<select>` in the app;
`datepicker.js` (291) replaces *every* date input. There are no native
dropdowns or date pickers anywhere in PostWarden. Add `confirm.js`
(107), `number-stepper.js` (82), the sidebar pair (98), and the
formatting/preference scripts.

`app/static/style.css` — 2,145 lines, **327 CSS custom properties, 21
themes**, 117 component classes. This is the most portable asset in the
repo: CSS variables work identically under React, and the themes should
come across essentially verbatim.

### Tests — 192 total, and the split matters more than the count

| Category | Count | Fate |
|---|---|---|
| Pure-Postgres invariants + cashflow | 60 | **Survive verbatim** |
| Assert DB state / status / headers | ~53 | Intent survives; mechanical port |
| Shallow text assertions | ~25 | Rewritable |
| Assert markup structure | ~49 | Mechanism dies, intent survives |

There is **no CI** — nothing runs the suite automatically today. There
are **no browser tests**. Blind spots with no coverage at all:
`GET /ledger` (456 lines, the largest handler in the app), all six XLSX
exports (~1,500 lines, and they emit live Excel formulas plus
conditional-formatting rules), `staging/duplicates` and its merge, the
entire mapped-import path, and every `/api/*` response body.

---

## 5. Decisions and rationale

Numbered in the style of `SPEC.md`, and for the same reason: the
rejected alternative is the useful half.

### 1. React, not Svelte or Vue — and not Next.js

React wins here on ecosystem fit for *this specific app*, not on
general merit. The hard problems are all dense-data-grid problems:
TanStack Table for Journal and Staging, TanStack Query for server state
(which is what `auto-refresh.js` polling is a hand-rolled substitute
for), React Hook Form + Zod for the entry form's dynamic line rows and
balance validation, Radix/shadcn for the combobox/datepicker/dialog
layer. Svelte is the nicer language and Vue the gentler curve; both are
thinner for financial data-grid UI specifically.

**Not Next.js, Nuxt, or Astro.** Choosing React is not choosing Next.
There is no SEO surface here and no public page — every screen is behind
`auth_gate`. Next would add a Node runtime to a deployment that is
currently one container plus Postgres, for zero benefit. Vite builds
static assets; FastAPI serves them via `StaticFiles`. **No Node at
runtime.**

### 2. Full backend restructure, not just routers plus an API

The narrower option — split `main.py` into `APIRouter`s, bolt JSON on,
change nothing else — was seriously considered and has one real
advantage: if the report math stays byte-identical, any wrong number in
the new UI is *definitionally* a frontend bug, which makes the whole
migration trivially debuggable.

Rejected because the restructure has to happen eventually, and doing it
later means a second disruption to a codebase that will by then have a
React frontend depending on its shape. Doing both at once costs
debuggability; doing them in sequence costs the work twice. The
debuggability loss is mitigated by §5.4 and by the fact that the ledger
itself cannot be corrupted (§3).

### 3. Vertical slices, not horizontal layers

`modules/entries/{router,schemas,service,repository}.py`, not
`models/ services/ views/`. Layer-oriented structure is the thing that
*produced* a 5,908-line `main.py`: every feature touches four
directories and every file grows forever. A module should be deletable
on its own; that is the test of whether the boundary is honest.

A pure `domain/` layer sits underneath with no framework or IO imports —
`money.py`, `periods.py`, `accounts.py`, `entry.py`. Accounting rules
that can be unit-tested in milliseconds without a database.

### 4. No golden-master capture of the current backend

This was planned, then rejected, and the reasoning is worth keeping
because it is counterintuitive.

The idea was to snapshot every report function's output against
`seed_demo.sql` and make the new backend reproduce it exactly. The
problem: **the current report numbers have never been validated.** The
existing tests hand-derive expected values only on toy data — 300
income, 100 + 50 expense, assert the running lines are 200 and 150,
arithmetic obvious by inspection. The hard paths *are* covered by named
tests (split-monthly column groups, Totals and Average columns,
partial-period asterisks, `pct_of_base` flipping, four cash-flow netting
rules) but those assert **behavior**, not numerical correctness against
a realistic book.

Capturing that output as "expected" would launder unvalidated behavior
into an authoritative-looking fixture — and would flag a *more correct*
new implementation as a regression. Worse than useless.

**Instead: port the test intent, not the test mechanism.** The ~49 tests
that die do so only because they regex-scrape HTML at
`tests/test_auth.py:1226`. Their intent survives intact and gets shorter
against a JSON API — `assert len(result["periods"]) == 3` beats a
`re.search` over `<td class="mono dim">`.

**Open, if numerical confidence is ever wanted:** build one hand-worked
example — a small book of 10–15 entries with income statement, balance
sheet and cash flow computed by hand once, used as a fixture. A few
hours, and it is information nobody currently has. Not a prerequisite
for any of this.

### 5. Alembic now, replacing the shelved numbered-migration mechanism

`CLAUDE.md` on `master` says not to add files to `db/migrations/`, and
that was right: every existing instance holds dummy data, so
`docker compose down -v` is cheaper than a migration.

That reasoning expires the moment an instance holds data worth keeping,
and this branch is where the app layer is being rebuilt anyway. Alembic
replaces the hand-rolled 55-line runner in `app/migrate.py`, with the
current `schema.sql` as the baseline revision. `schema.sql` itself stays
the source of truth for a fresh install.

### 6. One instance, not two — `master` is a git fallback, not a running comparison target

Originally planned as two live instances on separate volumes — the
existing Jinja app on one, the new backend on the other, both loaded
with `schema.sql` + `seed.sql` + `seed_demo.sql` — so report figures
could be diffed screen by screen against identical data.

Dropped. This is a committed, all-in rebuild, not a parallel-track
migration: `master` stays as a git-level fallback only, in case this
effort is abandoned, and nobody runs its app again otherwise — that
includes locally. Standing up and maintaining a second live container
for the sole purpose of number-diffing is ops overhead the plan no
longer needs.

`db/seed_demo.sql` stays exactly as useful, for a different reason: 418
lines, 58 journal entry and line inserts, hardcoded amounts, **zero
`random()`** — fully deterministic, so it is still the right fixture to
develop and test the one new instance against. Reproducible numbers on
every run; just not a second instance to compare them to.

Note that `seed.sql` alone seeds only accounts, scenarios and levels
with **no entries at all**. `seed_demo.sql` is mandatory here, not
optional.

If a specific figure ever needs a real cross-check, `master` can still
be checked out and run locally on demand, once, for that one number —
that capability costs nothing to keep and stays true. It is a fallback,
not standing infrastructure. Numeric confidence beyond the 60
pure-Postgres tests and each module's own tests comes from the
hand-worked fixture in decision 4 instead, if it's ever actually
wanted.

Entry ids are random 6-character codes (`SPEC.md` decision 17), so ids
will differ between instances. **Compare on `(date, description,
amount)`, never on id.**

### 7. Parity on what is actually used, decided per screen

All 26 screens get ported. But parity is judged against what is actually
exercised, not against an inventory — this is a single-user app and the
user is the authority on which details matter. Decide per screen and
record the drops; do not apply a blanket rule in either direction.

---

## 6. Roadmap

### Phase 1 — Backend

```
backend/src/postwarden/
├── main.py              # app factory + router mounting only
├── config.py · db.py
├── domain/              # pure logic, zero framework/IO imports
│   ├── money.py · periods.py · accounts.py · entry.py
├── modules/             # router · schemas · service · repository · tests
│   ├── entries/ · staging/ · budget/ · reports/ · imports/
│   ├── reference/ · scheduling/ · auth/
├── export/              # shared CSV/XLSX writers
└── analytics/           # star-schema views + the documented /api contract
```

Order: `domain/` first (pure, no database, fastest to verify), then
`modules/reports/` (where the hard ~450 lines live), then the rest.

- Port the hard functions **with their comments and docstrings intact**.
  They encode correctness properties that are not obvious from the code:
  double-counting avoidance in the "Net income after X" cell-by-cell
  sums, the union-of-activity scaffold in the split matrix, the
  three-way cash-flow tie-out invariant.
- Reports keep calling the existing Postgres SRFs — `fn_trial_balance`,
  `fn_cash_flow_lines`, `fn_rollup_balance`, `fn_account_balances`.
  **Do not model those through SQLAlchemy Core**; Core is for CRUD.
  Enums, generated columns and set-returning functions all model
  awkwardly and there is nothing to gain.
- Fix the `Decimal`/`date` JSON encoder centrally. This is a proven gap,
  not a theoretical one: `staging_duplicates_page` already hand-builds
  a parallel `groups_json` with `str(l["amount"])` to work around it,
  and `templates_full()` does the same.
- **CI lands with the first module** — GitHub Actions, `pytest` against
  a Postgres service container. The repo has none today.
- **Gate:** the 60 pure-Postgres tests pass unchanged, and every ported
  module's own tests are green, before any frontend work starts.

### Phase 2 — Frontend foundations

Vite + React + TypeScript, output served by FastAPI `StaticFiles`.
Typed client generated from the OpenAPI schema.

- Port the 327 CSS tokens and 21 themes essentially verbatim.
- Build the shell: sidebar with hover-preview and click-to-pin, topbar,
  flash banners, and the pre-paint theme/font restore that currently
  prevents FOUC via an inline `<head>` script.
- **Decide per widget** whether to adopt Radix/shadcn or port the
  existing JS. The current widgets encode real bug fixes: `e.code` not
  `e.key` because macOS Option remaps letters, explicit `tabIndex` for
  Safari's "text fields only" tab order, the iOS `select()` no-op.
  Off-the-shelf components will **not** be behavior-identical, and the
  difference is not always an improvement.

### Phase 3 — One screen per archetype (the go/no-go gate)

`UI_CONSISTENCY_AUDIT.md` §1 already establishes five archetypes. Build
one of each, in ascending risk:

1. **login** — proves the pipeline end to end
2. **tags** — Management/CRUD archetype
3. **trial balance** — Point-in-time report archetype
4. **Journal** — the hardest screen in the app

**If Journal does not come out clearly better than the Jinja version,
stop and reconsider.** Reaching that judgement early is the entire point
of this ordering.

### Phase 4 — Fill in by archetype

The remaining 22 screens are largely configuration once their archetype
component exists. Order: remaining reports → remaining CRUD → staging →
budget → duplicates → accounts.

### Phase 5 — The long tail

This is where rebuilds overrun. Budget for it explicitly.

- 21 themes × 26 screens visual pass
- Every `Alt+` shortcut, keyed on `e.code`, plus `option-key.js`'s ⌥
  relabeling on Apple hardware
- Confirm dialogs: always focus Cancel, trap Tab between exactly two
  buttons, red only for genuinely destructive actions (Reject and
  Delete — not Approve or Reverse)
- The debounced-autosave-with-corrective-POST on memo and description
  edit: Escape must undo a draft that already reached the server. This
  exists because of a real iPad bug.
- Tri-state (indeterminate) select-all on five screens, each clearing
  its selection when Select mode is turned off
- Per-thing localStorage keys — per sidebar group, per report table, per
  budget scenario. Collapsing one must never reset another.
- Report tree defaults differ by page: Accounts collapsed-first, reports
  expanded-first
- Distinct empty states per condition (nothing exists vs. nothing
  matches the filters), most with their own call to action
- `help.html`'s 225 lines of content, and the `?` deep-links into it

---

## 7. Verification

- The **60 pure-Postgres tests** stay green throughout, unchanged.
- Each module's ported tests green in CI.
- **Per screen:** verify against `db/seed_demo.sql`'s deterministic
  data — its figures are fixed and can be checked directly. Compare on
  `(date, description, amount)`, never on id, per decision 6. There is
  no standing second instance to diff against; check out `master`
  locally on demand if a specific figure ever needs a real cross-check.
- **Export parity:** byte-compare CSV and XLSX against current output.
  Zero coverage today, and the XLSX files carry live Excel formulas —
  the "Net income after X" rows are deliberately cell-by-cell sums
  (`=C6+C20-C34`) rather than ranges, because a rolled-up multi-level
  tree would double-count under `SUM()`.
- **Browser verification per screen**, as `CLAUDE.md` already requires
  for anything visual or interactive. Consider Playwright for the four
  flows that must never break: post an entry, approve from staging, run
  a report, export it.

## 8. Cutover

Merge `rebuild` into `master`, tag, deploy beta first, and exercise it
**authenticated**. An unauthenticated `303` sweep proves nothing:
`auth_gate` redirects before any route body — and therefore any query —
ever runs. This is the cutover, not a staged rollout: once beta is
confirmed good, the new app is what's live — there is no parallel Jinja
instance being kept running anywhere, per decision 6.

## 9. What would make us stop

Recorded up front, so it is a decision rather than a rationalization:

- **Journal does not come out better** at the Phase 3 gate.
- **The long tail stops converging** — Phase 5 items being discovered
  faster than they are closed.
- **The backlog stalls for longer than the rebuild is worth.** The whole
  justification is making future features cheaper. If the features stop
  mattering, so does this.

The fallback is cheap and should stay that way: `master` keeps working
as a git-level fallback, and its database is untouched — nothing about
this rebuild runs against it or depends on it running anywhere. That is
deliberate. Do not take actions that erode it.
