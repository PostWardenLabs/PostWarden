# Application architecture

How the code is organized and the conventions repeated across it. For
*what the database enforces and why*, see [`SPEC.md`](SPEC.md); for
*what the tables are*, see [`SCHEMA.md`](SCHEMA.md). This document is
about the FastAPI backend and the React + TypeScript frontend layered
on top of the schema those two describe.

Rewritten at cutover (`REBUILD.md`/`CLAUDE.md`'s own standing rule —
this file describes the *old* Jinja2 app throughout the `rebuild`
branch's life, deliberately stale until the branch actually lands).
Everything below describes the tree as it exists after that cutover:
a vertical-slice FastAPI backend (SQLAlchemy Core, no ORM) serving a
JSON API, and a separate React SPA consuming it through a generated,
typed client. `SPEC.md`'s decisions and the Postgres schema itself are
unchanged by any of this — this rebuild only ever touched the
application layer.

## The shape of it

No server-rendered HTML anywhere in the app itself (the SPA's own
`index.html` is a static file FastAPI hands out once, not a template
FastAPI renders per request). The backend is a pure JSON API — every
route returns a plain dict or a Pydantic model, `Decimal`-safe by
construction (see `json.py`). The frontend is a single-page app built
with Vite, routed client-side, talking to that API through a client
generated from the backend's own OpenAPI schema — a route that doesn't
exist, or a request body missing a required field, is a TypeScript
compile error, not a 404/422 discovered by clicking around.

```
db/schema.sql        tables, triggers, views, functions — the single source of truth
db/seed.sql           starter chart of accounts + ACTUAL/STAGING/BUD2026 scenarios
db/seed_demo.sql      optional sample entries (skippable)
alembic/              schema migrations forward from here — schema.sql stays the
                       baseline for a fresh install (REBUILD.md decision 5)

src/postwarden/main.py       app factory, router mounting, SPA serving — see below
src/postwarden/config.py     Settings — every env var the app reads, pydantic-settings
src/postwarden/db.py         the SQLAlchemy Core engine (lazy, process-wide, cached)
src/postwarden/errors.py     pg_message() — turns a raw Postgres trigger error into
                               the same user-facing string legacy's app/main.py used
src/postwarden/json.py       Decimal-safe JSON encoding, patched into FastAPI once
src/postwarden/cli.py        create-user / reset-password (see scripts/create_user.sh)
src/postwarden/domain/       pure business logic — money, periods, accounts, entry;
                               zero framework or IO imports, unit-testable with no DB
src/postwarden/modules/      one vertical slice per feature — see "Backend modules" below
src/postwarden/analytics/    the /api/* BI-consumer mirror + Connect Power BI/Excel
src/postwarden/export/       shared CSV/XLSX writers every module's own export.py calls
src/postwarden/static/       the built frontend (git-ignored — `npm run build` writes here)

frontend/                    the React + TypeScript SPA — see frontend/README.md and
                               "Frontend" below

apitests/                    the app layer's own suite — routes, services, repositories,
                               the domain layer (own top-level dir, not tests/api/ — see
                               apitests/conftest.py for why nesting under tests/ doesn't work)
tests/test_invariants.py     the schema's own rules, asserted straight against Postgres,
tests/test_cashflow.py        never importing the app — REBUILD.md §3's "60 pure-Postgres
                               tests," the actual safety net this rebuild leaned on

scripts/init_db.sh                 local database bootstrap
scripts/create_user.sh             create or reset a login
scripts/dump_openapi_schema.py     regenerates frontend/'s typed API client
deploy/gcp/                        a fully-worked example of running this on Google
                                     Cloud — not how demo/beta are actually run
```

## Backend: vertical-slice modules over SQLAlchemy Core

`REBUILD.md` decision 3 is the one structural choice everything else in
`src/postwarden/` follows from: **Core, not the ORM** — Postgres itself
already enforces the real invariants (double-entry balance, immutability,
account hierarchy) through triggers, and an ORM's identity map/unit-of-
work would fight that rather than help it. Every module composes typed,
explicit SQL through Core instead.

Each feature under `modules/` is a **vertical slice**, own subdirectory,
consistent internal shape:

| File | Owns |
|---|---|
| `router.py` | The `APIRouter` — route signatures, query/path param parsing, calls into `service.py`, returns the result. No SQL, no business logic. |
| `service.py` | The actual logic — validation, orchestration across multiple repository calls, anything that isn't "shape an HTTP request into a function call" or "run one query." |
| `repository.py` | Raw SQL access through the shared `Connection` (`db.get_connection()`) — `text()` calls, not `Table`/`select()` Core constructs, wherever the schema's enum types/generated columns/set-returning functions would model awkwardly through Core with nothing gained (`reports/repository.py`'s own docstring is the fullest statement of this — reports read the existing `fn_trial_balance`/`fn_cash_flow_lines`/etc. Postgres functions directly rather than reinventing them in Core). |
| `schemas.py` | Pydantic request-body models, where a module actually has a POST/PATCH body worth validating declaratively. Several modules (`reports`, `analytics`) have none at all — a GET with plain query params needs no schema, and response shapes stay plain dicts throughout (no response-model layer) since the OpenAPI generation step (`frontend/`'s `generate:api`) only ever needed request-side types to produce a useful client. |

`REBUILD.md` decision 3's other half — "a module should be deletable on
its own" — is why sibling modules each fork a small private copy of a
helper (an account-id lookup, a filter-fragment builder) rather than
import it from another business module. The one deliberate exception is
`modules/auth/` (`deps.py`, `service.py`): every other module
unconditionally depends on there being a logged-in user at all, so
importing auth's session/CSRF helpers directly — rather than forking
them nine times over — is the honest expression of that dependency, not
a violation of it. See `modules/auth/deps.py`'s own docstring.

**Current modules** (`src/postwarden/modules/`): `auth` (sessions, CSRF,
account settings), `entries` (the Journal), `staging` (import review +
duplicates), `reports` (Trial Balance, Balance Sheet, Income Statement,
Cash Flow, Variance, Ledger — the ~450 lines `REBUILD.md` §6 calls out
as "genuinely hard," ported close to verbatim), `imports` (plain-CSV and
mapped/rules importers), `budget` (budget lines + variance), `reference`
(Accounts, Payees, Tags, Scenarios, Account Levels — reference-data
CRUD), `scheduling` (scheduled entries + entry templates), `dashboard`
(the landing page — the one module with no legacy JSON precedent at
all, built fresh in Phase 4.7). `src/postwarden/analytics/` sits
alongside `modules/` rather than inside it — it's not one feature but a
cross-cutting mirror (`GET /api/accounts`, `/api/entries`, `/api/trial-
balance`, etc.) plus the Connect Power BI/Excel settings routes, a real
external contract (saved `.pbids` files point at these exact URLs)
that predates and outlives any one module.

`domain/` (`money.py`, `periods.py`, `accounts.py`, `entry.py`) is
different in kind from `modules/`: pure functions, no `Connection`
parameter, no FastAPI import, nothing that needs Postgres running to
test. Account-tree building/flattening, period-splitting, and the pure
half of the reports logic all live here rather than in `modules/
reports/service.py`, specifically so they stay unit-testable in
milliseconds. This is also why `apitests/domain/` has no database
fixtures at all, unlike every other `apitests/` subdirectory.

## Auth: per-route dependency, not global middleware

Legacy's `auth_gate` was a single piece of ASGI middleware ahead of
every route. The rebuilt backend does the equivalent per-route instead:
every module's `APIRouter` sets `get_current_session` (`modules/auth/
deps.py`) at its own router-level `dependencies=[...]`, and every write
route additionally depends on `require_csrf_header`. An absent/expired
session is a plain `401` JSON body — there's no login *page* on the
backend side for it to redirect to; the frontend's `SessionProvider`
(below) is what turns a `401` into the login screen.

The one piece of `auth_gate` that doesn't fit a per-route dependency —
lazily materializing due schedules on every authenticated request
(`SPEC.md` decision 9: no task runner, so "auto-post on the date"
happens inline) — is the one real middleware `main.py` still adds
(`advance_due_schedules`), gated on there being a valid session cookie,
otherwise a no-op. See `main.py`'s own module docstring for the full
reasoning, including why this is the *only* thing kept as middleware.

## `main.py`: mounting, not logic

`main.py` owns no routes of its own beyond `/healthz`, `/config`, and
the SPA-serving routes below — every module's router is `include_
router`'d in, and that's the whole of what this file does route-wise.
Two things worth knowing if you're tracing a request:

- **`/app/*`, not `/api/*`, is the SPA's namespace.** The obvious-
  looking choice — prefixing every JSON route with `/api` — turns out
  to collide with `analytics/router.py`'s own real, already-shipped
  `/api/accounts`, `/api/entries`, etc. (a different, flatter shape
  than the module routes of the same name). So the SPA's client-side
  routes live under `/app/*` instead, a namespace no backend router has
  ever used; zero module routes changed to make room for it. `GET
  /entries` is still the Journal's own JSON data route; `/app/entries`
  is the page a browser navigates to.
- **The SPA is served last, and only if built.** `StaticFiles(html=True)`
  is mounted at `/` after every module router, so a module's own path
  always wins a collision; `postwarden_static_dir` not existing (a
  backend-only checkout, CI, a module test suite) is a supported state,
  not an error — nothing 500s over a missing `static/`. Two small
  routes (`/app`, `/app/{path:path}`) exist solely to serve the same
  `index.html` for a direct browser navigation/refresh at a client-side
  route with no matching file on disk — React Router takes over from
  there once the bundle loads; the `path` param itself is never
  inspected.

## Frontend: React SPA, one component per archetype

`frontend/src/App.tsx` is the router root — a three-way branch on
session status (`loading` / `anonymous` → `LoginPage` / authenticated →
the real `<Routes>`), wrapping every screen in `Shell` (topbar + sidebar
navigation, `shell/`). `main.tsx` mounts `SessionProvider` and
`BrowserRouter` above `App` itself.

```
frontend/src/
  main.tsx, App.tsx        entry point, routing, session-gated branch
  api/client.ts             the one openapi-fetch client every screen imports
  api/schema.ts              generated — see frontend/README.md's generate:api
  api/use*.ts                 small hooks wrapping one reference-data GET each
                              (useAccounts, useScenarios, useTags, ...)
  auth/                      SessionProvider, LoginPage, the session React context
  shell/                     Shell, Sidebar, Topbar, FlashBanner, nav.ts's route table
  widgets/                   shared building blocks — see "Widgets" below
  format/                    money/date formatting, cents-entry parsing, shortcut keys
  reports/                  DashboardPage + the six report screens
  journal/, staging/, budget/, tags/, setup/   one directory per feature area,
                                                  mirroring src/postwarden/modules/
                                                  roughly 1:1 but not rigidly —
                                                  setup/ bundles several small
                                                  Management/CRUD screens together
```

**The typed API client** (`api/client.ts` + generated `api/schema.ts`)
is what makes a backend route change a compile-time frontend event
instead of a runtime surprise: `openapi-typescript` turns every route,
query/path param, and Pydantic request body under `src/postwarden/
modules/*/router.py` + `schemas.py` into TypeScript types; `client.ts`
wraps them in an `openapi-fetch` client that also attaches
`X-CSRF-Token` to every non-`GET` request and notifies `SessionProvider`
on any `401` (the SPA's equivalent of legacy's redirect-to-`/login` on
a stale cookie). See `frontend/README.md` for the regeneration command
— this file stays a pointer, not a duplicate, of that doc's own
mechanics.

A route with no Pydantic response model (most of them — response
shapes stay plain dicts backend-side, per the modules table above)
types as `{[key: string]: unknown}` in the generated schema; every
screen that reads one casts through a small local `interface` matching
what the route's own docstring promises, rather than threading `unknown`
through the component. This is a real, repeated, deliberate gap — not
fixed by adding response models backend-side, since nothing about the
Pydantic-free response shape has actually caused a bug.

### Component archetypes

`UI_CONSISTENCY_AUDIT.md` §1 named five page shapes before any of this
was rebuilt; on this branch that stops being a review convention and
becomes the actual build order — one component per archetype, then
per-screen configuration, not a bespoke page per screen:

| Archetype | Screens | Shared shape |
|---|---|---|
| Filterable transaction list | Journal, Staging | URL-state filters, a paginated/scrollable table |
| Point-in-time report | Trial Balance, Balance Sheet, Variance, Ledger | scenario + "as of" date, `useCollapsibleTree` for the account tree (Ledger is flat cards instead — no hierarchy to collapse) |
| Range/period report | Income Statement, Cash Flow | scenario + date-from/date-to, `PeriodPresetPicker` |
| Editable grid | Budget | live client-side recompute, no full-page reload on edit |
| Management / CRUD | Accounts, Payees, Tags, Scenarios, Account Levels, Scheduled Entries, Templates | Select/Merge/+Add/table/Status/Archive — `useSelectMode`, `MergeDialog` |

Every Point-in-time and Range/period report screen also carries the
`entry_link`/`cell_link` drill-through pattern ported from legacy's own
Jinja macros: a non-zero (or, on Balance Sheet, any leaf) amount is a
real `<Link className="amount-link">` to `/app/entries` pre-filtered to
`scenario`/`date_from`/`date_to`/`account` — each report's own date-
bounding rule differs (see each page's own `entryLink`/`cellLink`
comment), ported exactly rather than unified into one shared rule.

### Widgets

`widgets/` holds the pieces reused across archetypes rather than tied
to one screen: `Combobox`, `DatePicker`, `NumberStepper`, `TagInput`,
`ConfirmDialog`, `MergeDialog`, `FileField`, `PeriodPresetPicker`, plus
three hooks — `useCollapsibleTree` (account-tree expand/collapse state,
persisted per report to `localStorage`), `useSelectMode` (the
Management/CRUD archetype's row-selection state), `useInlineEdit`. Most
of these exist specifically to reproduce a real browser-quirk fix the
legacy vanilla-JS files already had and an off-the-shelf component
would not: `DatePicker`'s digit/hyphen input filtering, explicit
`tabIndex` for Safari's tab order, `option-key.js`'s `e.code`-not-`e.key`
shortcut handling (`format/shortcut.ts` now).

## Testing

Three suites, deliberately never sharing a single pytest invocation
(see `apitests/conftest.py` and `.github/workflows/backend-ci.yml`'s
own comments for the mechanics of why):

- **`tests/test_invariants.py` + `tests/test_cashflow.py`** — the 60
  pure-Postgres tests, unchanged by this entire rebuild. Talk to
  Postgres directly, never import the app package at all.
- **`apitests/`** — the app layer's own suite: `domain/` (no database),
  `modules/*/test_repository.py` + `test_service.py` + `test_router.py`
  per module, `export/`, `analytics/`, plus `test_config.py`/`test_db.py`/
  `test_main.py`/etc. for the small pieces outside any one module. Its
  own `conftest.py` provisions a disposable `postwarden_backend_test`
  database from `db/schema.sql` alone (no seed data) — every test
  builds its own minimal fixture rows.
- **Frontend** — no automated test runner as of cutover; verification is
  manual browser checking against `db/seed_demo.sql`'s deterministic
  data (`REBUILD_STATUS.md`'s own standing verification checklist),
  plus `tsc -b` (part of `npm run build`) as the type-correctness gate.

CI (`.github/workflows/backend-ci.yml`) runs the first two as two
separate jobs against two separate Postgres service containers — kept
apart because they provision their schema two different ways (raw SQL
file vs. Alembic) and importing the app package in the same process as
`tests/conftest.py`'s own `pytest_configure` would collide.
