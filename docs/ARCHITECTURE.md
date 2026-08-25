# Application architecture

How the code is organized and the conventions repeated across it. For
*what the database enforces and why*, see [`SPEC.md`](../SPEC.md); for
*what the tables are*, see [`SCHEMA.md`](SCHEMA.md). This document is
about the FastAPI app, the templates, and the static JS/CSS layered on
top of the schema those two describe.

## The shape of it

No ORM, no build step, no SPA framework — server-rendered Jinja2 HTML,
plain SQL through psycopg3, and small vanilla-JS files that each
progressively enhance one specific thing (a `<select>` becomes a
searchable combobox, a `<input type="date">` gets a calendar popup, a
table gets collapsible rows) rather than one big client-side framework
owning the page. A page works — link-navigable, forms submit — with
JS disabled; JS makes it nicer, never load-bearing for anything but a
few real-time conveniences (live budget-grid recompute, the live balance
bar on New entry) that have no meaningful no-JS equivalent anyway.

```
db/schema.sql        tables, triggers, views, functions — the single source of truth
db/seed.sql          starter chart of accounts + ACTUAL/STAGING/BUD2026 scenarios
db/seed_demo.sql     optional sample entries (skippable)

app/main.py          every route, in one file (see the map below)
app/auth.py          sessions, password hashing, CSRF, login rate-limiting
app/db.py            the psycopg3 connection pool — q()/q1()/tx() helpers main.py calls
app/cli.py           create-user / reset-password (see scripts/create_user.sh)
app/templates/*.html one file per screen, all extending base.html
app/static/*.js      one small file per progressive enhancement (catalog below)
app/static/style.css theme variables + every component's styling, hand-written, no framework

tests/test_invariants.py  hits Postgres directly — the schema's own rules, bypassing the app entirely
tests/test_auth.py        drives the actual FastAPI app (TestClient) — routes, sessions, CSRF, rendering
deploy/gcp/               Google Cloud deployment (Compute Engine + IAP tunnel) — see its own README
```

`app/main.py` is deliberately one file (~2100 lines as of the Budget
page). That's a real tradeoff, not an oversight: every route is
`grep`-able in one place, there's no question of which module owns a
helper, and "thin application, no ORM" (SPEC.md decision 7) has held up
well enough in practice that splitting it hasn't paid for itself yet. If
it ever does get split, the section markers below are the natural seams.

## `app/main.py`, by section

The file is organized top-to-bottom as: shared helpers → one section per
screen, each with its route(s) and any private `_helper` functions that
section alone needs → the JSON `/api/*` mirror at the very end. In
reading order:

| Section | Routes | Notes |
|---|---|---|
| Auth | `/login`, `/logout` | `require_csrf()` here is called by every other state-changing route |
| Settings | `/settings/*` | username/password change, theme preference |
| Dashboard | `/` | always ACTUAL — "how are my real finances doing," no scenario picker |
| Trial balance | `/trial-balance`, `/export/trial-balance.csv` | `_build_account_tree`/`_flatten_tree` (defined here) are reused by Balance Sheet and the Budget page |
| Income statement | `/income-statement`, `/export/income-statement.csv` | the only report with a date *range* (not "as of") and a two-scenario compare column |
| Balance sheet | `/balance-sheet`, `/export/balance-sheet.csv` | |
| Budget | `/budget`, `/budget/cell` | `_budget_rows()` builds two account-trees (budgeted, actual) and merges them node-for-node — see [the pattern below](#the-account-tree--rollup-pattern) |
| Variance | `/variance`, `/export/variance.csv` | general two-scenario diff, rolled up to a common `account_levels` depth |
| Chart of accounts | `/accounts`, `/accounts/quick-create` | |
| Journal entry create | `/entries` POST | `_parse_lines()` turns the grid's parallel `account[]/debit[]/credit[]` arrays into line dicts |
| Journal browser | `/entries` GET, `/entries/export.csv`, `/entries/{id}/reverse` | `_entries_filter()` builds the one WHERE clause both the HTML view and the CSV export share |
| Scenarios | `/scenarios`, `/scenarios/{id}/toggle-lock` | create + lock-toggle only — no edit, no delete (see SCHEMA.md) |
| Account levels | `/account-levels` | |
| Payees | `/payees`, `/payees/quick-create` | quick-create is called via `fetch()` from the New entry payee combobox |
| Scheduled entries | `/scheduled` | `materialize_due_schedules()` runs lazily on request (no cron in this deployment), posting each due occurrence into Staging |
| Staging | `/staging`, `/staging/approve` | review/approve page for whatever's sitting in the one `is_staging` scenario — checkboxes + "Approve entries" copies each into its real target scenario and sets `promoted_entry_id`; `pending_staging_entries()` is the shared query the Dashboard's banner count also uses |
| Import | `/import` | uploads a CSV in `/entries/export.csv`'s own column layout; `_parse_csv_import()` groups rows by `Entry #` and fully validates every group in Python before anything touches the database, then stages the valid ones in Staging under a new `import_batches` row |
| Entry templates | `/templates` | scaffolding only — loading one is client-side, nothing tracked server-side |
| `/api/*` | JSON mirror | same data as the HTML screens, for scripts; not used by the app's own pages |

## Templates

Every template `{% extends "base.html" %}`, which owns the `<head>`
(theme pre-paint script, so a saved theme applies before first paint),
the sidebar nav, the flash-message banner, and three blocks a page fills
in: `title`, `content`, and `scripts` (page-specific `<script src>` tags
— a page needs this block only for something `base.html` doesn't already
load unconditionally: `combobox.js`, `datepicker.js`, `sidebar.js`,
`theme.js`, `cents-entry.js`, `money-format.js`, `auto-refresh.js`.
`tags.js` is the one common enhancement that *isn't* always-on — only
pages with an actual tag input (`entries.html`, `scheduled.html`, ...)
load it themselves).

`request.state.user` (set by the auth middleware) carries `csrf_token` —
every state-changing `<form>` reads it directly as
`{{ request.state.user.csrf_token }}` rather than the route passing it
through the template context explicitly.

## Static JS, one enhancement per file

| File | Enhances |
|---|---|
| `app.js` | The journal-entry line grid (New entry) — keyboard flow, live balance bar, fetch-based submit so a rejected entry doesn't lose what you typed. |
| `auto-refresh.js` | Every `<form class="bar" method="get">` — a delegated `change` listener submits the form the moment a `<select>` or date/month field changes, so a report or the Journal's filters refresh without a separate Refresh/Filter click. |
| `budget-grid.js` | The Budget page's editable cells — live client-side subtotal recompute plus per-cell autosave on blur. |
| `combobox.js` | Every `<select>` on the page, into a searchable/filterable dropdown. |
| `datepicker.js` | Every `<input type="date">`, into a calendar popup (still submits a plain `YYYY-MM-DD`). |
| `tags.js` | The tag chip input (select-or-create, comma-separated hidden value underneath). |
| `entry_templates.js` | "Load template" on New entry — fills the grid client-side from a page-embedded JSON blob. |
| `cents-entry.js` | Optional "digits fill in from the right" amount entry (POS-terminal style), toggled in Settings. |
| `accounts.js` | The Chart of Accounts page's collapsible tree, plus its inline "+" add-category form. |
| `report-tree.js` | The same collapse/expand interaction, reused on Trial Balance/Balance Sheet/Budget — smaller than `accounts.js` since reports don't need the add-category form. Defaults *expanded* (reports are for reading numbers); Accounts defaults *collapsed* (browsing structure). |
| `period-picker.js` | The date-range preset dropdown on Income Statement — fills in the two real `date_from`/`date_to` inputs; the backend never sees the preset itself. |
| `money-format.js` | Rewrites every `{{ x | money }}` span's displayed text using the symbol/decimal/thousands preference saved in Settings. Also exposed as `window.LibroMoney.format()` for the handful of places (the New entry balance bar, `budget-grid.js`) that compute a total client-side and need the same formatting without a `{{ }}` span to rewrite. |
| `sidebar.js` | Hover-to-preview / click-to-pin hamburger nav. |
| `staging.js` | The Staging page — "select all" toggles every entry checkbox; both Approve buttons stay disabled until at least one is checked. |
| `theme.js` | The theme `<select>` in Settings; the pre-paint switch itself lives inline in `base.html`. |

## Patterns used more than once

Rather than re-explain these at every call site, here's each one, once.

### The account-tree / rollup pattern

Trial Balance, Balance Sheet, and the Budget page all show the same
kind of thing: a hierarchical chart of accounts where a summary account
(e.g. "Current Assets") needs to display the *sum* of everything under
it, not just its own direct postings, and the whole thing needs to
collapse/expand.

- **Server side** (`app/main.py`): `_build_account_tree(accounts,
  balances_by_id)` takes the flat account list (from `v_dim_account`)
  and a `{account_id: balance}` map, builds the parent/child forest, and
  rolls each node's `subtotal` up from its own balance plus every
  descendant's. `_flatten_tree(nodes, zeros)` walks it depth-first for
  template rendering, dropping a zero-subtotal subtree unless `zeros`.
  The Budget page needs *two* numbers per node (Budgeted and Actual), so
  `_budget_rows()` calls `_build_account_tree` twice and merges the two
  trees node-for-node rather than teaching the tree builder about
  multiple values — see its own comment for why.
- **Markup**: every row carries `data-id`, `data-parent`, and
  `data-has-children` on the `<tr>`, and an (initially empty) `<span
  class="tree-toggle">` in the name cell — the chevron itself is pure
  CSS (a rotated border-corner, not a font glyph; see `style.css`'s
  `.tree-toggle::before`), shown only via a `tr[data-has-children="1"]`
  selector so a leaf row's span stays empty but still reserves the
  indent width.
- **Client side**: `report-tree.js` (or `accounts.js` on the Accounts
  page) reads those `data-*` attributes to hide/show descendant rows and
  persist collapse state in `localStorage`, keyed by a
  `data-collapse-key` on the `<table>`.

### Click an amount → filtered Journal, with a back link

Income Statement, Balance Sheet, Trial Balance, and Payees all link a
number through to the Journal filtered to exactly what produced it, with
a way back.

- Each report template defines an `entry_link(code, value)` Jinja macro
  building `href="/entries?...&account={{ code }}&back={{ report_url |
  urlencode }}"`, where `report_url` is that same template's own current
  URL (`{% set report_url = "/trial-balance?scenario=" + ... %}`) —
  every filter/toggle the report currently has applied comes back with
  you. Payees does the same thing with `payee={{ name }}` instead of
  `account`.
- Only **leaf** rows link (`if not r.has_children`) — a summary row's
  subtotal spans multiple accounts, and no single Journal filter
  captures "everything under this node," so it stays plain text. This is
  a deliberate v1 scope decision, applied consistently everywhere the
  pattern appears.
- `entries_page()` accepts `account`/`payee` and validates `back` is a
  same-origin relative path (`back.startswith("/")` and not `"//"`,
  ruling out an off-site redirect) before rendering `entries.html`'s "←
  Back to report" link. `_entries_filter()` is the one place the
  resulting WHERE clause is built, shared by the HTML view and the CSV
  export so what you see is exactly what you'd export.

### Inline creation via `fetch()`, not a full-page POST

New entry (`app.js`) and the Budget grid (`budget-grid.js`) both submit
via `fetch()` with `Accept: application/json` instead of a normal form
POST, specifically so a *rejected* submission (an unbalanced entry, an
unknown account code) can show its error in place without a redirect
losing everything already typed. The route itself checks
`"application/json" in request.headers.get("accept", "")` and returns
`JSONResponse({"ok": False, "error": ...})` instead of `flash_redirect()`
when that header is present — every such route still supports a plain
form POST too (the `wants_json` branch is additive), so it degrades
gracefully without JS.

### Auto-refreshing filter bars

Every report's filter form and the Journal's are `<form class="bar"
method="get">` — a plain GET, so the current filters are always a
bookmarkable/shareable URL, no client-side state involved. `auto-refresh.js`
is one delegated `change` listener per such form (found by that same
class + method, no opt-in markup needed on individual fields) that calls
`form.requestSubmit()` the moment a `<select>` or date/month field
changes. It's a `change` listener on the *form*, not on each field, so it
needs no re-binding when combobox.js/datepicker.js swap a plain `<select>`/
`<input type="date">` for their own enhanced markup — both of those
already dispatch a real bubbling `change` on the original element when a
value is picked (see their own files), which is all a bubble-phase
listener on an ancestor ever needed. Deliberately scoped to selects and
date-ish fields only: a text field (Search, the Amount value) or the tag
picker never matches, so typing never triggers a mid-word navigation —
only a deliberate pick does.

### Flash messages

`flash_redirect(url, ok=, err=)` / `flash_url(...)` append `?ok=...` or
`?err=...` to a redirect target; `base.html` renders whichever is
present as a banner. Stateless on purpose — no session-stored flash
queue to forget to clear.

### CSRF

`require_csrf(request, token)` (in `main.py`) compares the submitted
`csrf_token` against `request.state.user.csrf_token` with
`secrets.compare_digest`. Every state-changing route calls it as the
first line of its `try:` block, so a bad/missing token fails exactly
like any other validation error (a flashed `err=`, not a 500).

## Tests

`tests/test_invariants.py` talks to Postgres directly (no FastAPI
involved) — it's asserting what SPEC.md and SCHEMA.md claim the
*database itself* refuses, so it has to bypass the app to be meaningful.
`tests/test_auth.py` drives the real app through `TestClient` — routes,
templates, session/CSRF handling, the things only the app layer
enforces. Both share `tests/conftest.py`'s `mk_*` row-builder helpers and
get a disposable `libro_test` database per run (dropped and recreated
from `db/schema.sql` + `db/seed.sql` — no demo data — via
`pytest_configure`).

Run them (from the repo root, with `docker compose up -d db` already
running):

```bash
LIBRO_TEST_ADMIN_URL=postgresql://libro:libro@localhost:5432/postgres \
LIBRO_TEST_URL=postgresql://libro:libro@localhost:5432/libro_test \
pytest -q
```

See the README's own "Tests" section for the Docker-network variant that
needs no local Postgres client at all.
