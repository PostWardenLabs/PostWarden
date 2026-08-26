# Application architecture

How the code is organized and the conventions repeated across it. For
*what the database enforces and why*, see [`SPEC.md`](SPEC.md); for
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
db/migrations/       NNN_*.sql — applied to an *existing* database only, see app/migrate.py

app/main.py          every route, in one file (see the map below)
app/auth.py          sessions, password hashing, CSRF, login rate-limiting
app/db.py            the psycopg3 connection pool — q()/q1()/tx() helpers main.py calls
app/migrate.py       run_migrations() — called once from main.py's lifespan, before the app serves traffic
app/cli.py           create-user / reset-password (see scripts/create_user.sh)
app/templates/*.html one file per screen, all extending base.html
app/static/*.js      one small file per progressive enhancement (catalog below)
app/static/style.css theme variables + every component's styling, hand-written, no framework

tests/test_invariants.py  hits Postgres directly — the schema's own rules, bypassing the app entirely
tests/test_auth.py        drives the actual FastAPI app (TestClient) — routes, sessions, CSRF, rendering
tests/test_migrations.py  app/migrate.py's own mechanism — real files, real Postgres, no mocking
deploy/gcp/               Google Cloud deployment (Compute Engine + IAP tunnel) — see its own README
```

`app/main.py` is deliberately one file (~2100 lines as of the Budget grid). That's a real tradeoff, not an oversight: every route is
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
| Auth | `/login`, `/logout` | `require_csrf()` here is called by every other state-changing route; "Remember me" only changes whether the session cookie carries a `Max-Age` (see README's Security notes), the session row itself is always 30 days. `POSTWARDEN_DEMO_MODE=true` (off by default, only set on the public demo) shows a banner on `login.html` and pre-fills the username/password fields with `POSTWARDEN_ADMIN_USER`/`PASSWORD` — server-rendered `value=` attributes, no JavaScript, so the credentials are genuinely visible in the page rather than silently injected. Deliberately a *second* flag rather than triggering off `POSTWARDEN_ADMIN_USER`/`PASSWORD` being set alone — those two are also the normal self-hoster first-boot convenience, and this keeps a self-hoster's own real password from ever appearing on their own login page |
| Settings | `/settings`, `/settings/account`, `/settings/connect-bi`, `/settings/connect-bi/download.pbids` | theme/amount-entry/number-format preferences on the first; username and password change split onto the second (`account.html`) — security-sensitive actions, kept off the page you land on by default. `connect_bi.html` shows the `postwarden_bi` read-only role's host/port/database (SPEC.md decision 14) — host/port come from `request.url.hostname`/`POSTWARDEN_BI_PORT` since they're the only two things that vary per install; the `.pbids` route hands back the same two as a downloadable Power BI Data Source file, no credentials in it |
| Dashboard | `/` | always ACTUAL — "how are my real finances doing," no scenario picker |
| Trial balance | `/trial-balance`, `/export/trial-balance.csv` | `_build_account_tree`/`_flatten_tree` (defined here) are reused by Balance Sheet and the Budget grid |
| Income statement | `/income-statement`, `/export/income-statement.csv` | the only report with a date *range* (not "as of") and a two-scenario compare column |
| Balance sheet | `/balance-sheet`, `/export/balance-sheet.csv` | |
| Budget grid | `/budget`, `/budget/cell` | `_budget_rows()` builds two account-trees (budgeted, actual) and merges them node-for-node — see [the pattern below](#the-account-tree--rollup-pattern) |
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
| Help | `/help` | static reference content, one `<h2 id="...">` section per screen — the explanatory prose that used to sit atop every page individually now lives here once, in a two-column layout (`.two-col`/`.side-nav`, [see below](#sticky-side-nav-layout)) with its own jump-to nav; every other page links back with a small "?" icon in its own top-right corner (`.page-head`/`.help-icon`) rather than a sentence of caption text |
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
| `app.js` | The journal-entry line grid, shared by New entry, Scheduled, and Entry templates — keyboard flow (Tab, and Enter/Shift+Enter through the same account → debit → credit → memo → next row order, overriding a plain text input's default of submitting the form), live balance bar, fetch-based submit so a rejected entry doesn't lose what you typed, and Distribute (fills whichever line has focus with whatever amount, on whichever side, zeroes the entry out — always overwrites that line rather than adding to it). |
| `auto-refresh.js` | Every `<form class="bar" method="get">` — a delegated `change` listener submits the form the moment a `<select>` or date/month field changes, so a report or the Journal's filters refresh without a separate Refresh/Filter click. |
| `budget-grid.js` | The Budget grid's editable cells — live client-side subtotal recompute plus per-cell autosave on blur. |
| `combobox.js` | Every `<select>` on the page, into a searchable/filterable dropdown. |
| `datepicker.js` | Every `<input type="date">`, into a calendar popup (still submits a plain `YYYY-MM-DD`). |
| `number-stepper.js` | Every `<input type="number">` (Account levels' Depth, Scheduled's "Repeats every") — hides the browser's native spinner and adds the site's own chevron up/down buttons; typing and the keyboard's own arrow keys still work, input stays `type="number"` throughout. |
| `tags.js` | The tag chip input (select-or-create, comma-separated hidden value underneath). |
| `entry_templates.js` | "Load template" on New entry — fills the grid client-side from a page-embedded JSON blob. |
| `cents-entry.js` | Optional "digits fill in from the right" amount entry (POS-terminal style), toggled in Settings. |
| `accounts.js` | The Chart of Accounts page's collapsible tree, plus its inline "+" add-category form. |
| `report-tree.js` | The same collapse/expand interaction, reused on Trial Balance/Balance Sheet/Budget grid — smaller than `accounts.js` since reports don't need the add-category form. Defaults *expanded* (reports are for reading numbers); Accounts defaults *collapsed* (browsing structure). |
| `period-picker.js` | The date-range preset dropdown on Income Statement — fills in the two real `date_from`/`date_to` inputs; the backend never sees the preset itself. |
| `money-format.js` | Rewrites every `{{ x | money }}` span's displayed text using the symbol/decimal/thousands preference saved in Settings. Also exposed as `window.PostWardenMoney.format()` for the handful of places (the New entry balance bar, `budget-grid.js`) that compute a total client-side and need the same formatting without a `{{ }}` span to rewrite. |
| `sidebar.js` | Hover-to-preview / click-to-pin hamburger nav. |
| `staging.js` | The Staging page — "select all" toggles every entry checkbox; both Approve buttons stay disabled until at least one is checked. |
| `theme.js` | The theme `<select>` in Settings; the pre-paint switch itself lives inline in `base.html`. |

## Patterns used more than once

Rather than re-explain these at every call site, here's each one, once.

### The account-tree / rollup pattern

Trial Balance, Balance Sheet, and the Budget grid all show the same
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
  The Budget grid needs *two* numbers per node (Budgeted and Actual), so
  `_budget_rows()` calls `_build_account_tree` twice and merges the two
  trees node-for-node rather than teaching the tree builder about
  multiple values — see its own comment for why.
- **Markup**: every row carries `data-id`, `data-parent`, and
  `data-has-children` on the `<tr>`, and an (initially empty) `<span
  class="tree-toggle">` in the name cell — the chevron itself is pure
  CSS (a solid `.chevron` clip-path triangle, not a font glyph; see
  `style.css`'s `.tree-toggle::before`), shown only via a
  `tr[data-has-children="1"]` selector so a leaf row's span stays empty
  but still reserves the indent width.
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

### Sticky side-nav layout

Accounts (browse by level) and Help (jump to a section) both need the
same shape: a narrow list of links on the left that stays in view while
a longer, scrollable body sits on the right. One CSS pattern covers
both — `.two-col` (flex row) wrapping a `.side-nav` (`position: sticky`,
fixed width) and a `.two-col-main` (`flex: 1`). `.side-nav a.active`
marks the current entry; Accounts sets it server-side per request
(which level is selected), Help has no equivalent since its nav links
are same-page anchors, not separate pages, so it's left unset there.
Named for what it is rather than its first caller (it started as
Accounts-only, back when it was `.accounts-layout`/`.levels-panel`).

### The page title lives in the topbar, not the content

No template has its own `<h1>PageName</h1>` any more — `base.html`'s
topbar-left renders `{{ self.title() }}` (Jinja's way to call a
`{% block %}` from outside where it's defined) followed by a muted
`<span class="wordmark-brand"> · PostWarden</span>`, reusing the exact same
`{% block title %}` every page already sets for `<title>Dashboard ·
PostWarden</title>`. One string, two places, always in sync — there's no
second place to update when a page's name changes. A page that still
needs a top-right "?" help icon keeps a `.page-head` div for it
(`justify-content: flex-end` now that it has nothing to space against);
a page with neither just starts straight into its content.

`.topbar` itself is pure chrome (full-bleed background/border, no
horizontal padding) — the title lines up with the page content beneath
it because `.topbar-inner`, wrapping `.topbar-left`/`.topbar-right`,
uses the exact same `max-width: 1080px; margin: 0 auto; padding: 0
1.25rem` box model as `main` itself, including the same
`html.sidebar-pinned` override (`margin-left: 14rem`, `main`'s own
`margin-right` stays `auto` so it sits flush after the sidebar rather
than re-centering in what's left — `.topbar-inner` copies that exact
behavior too). An earlier version tried to *approximate* main's
centering with a `calc()` on `.topbar-left` instead of literally sharing
main's own properties, and got it wrong two ways at once worth
remembering next time something needs to track another element's layout
this closely: `100vw` includes the scrollbar where a real containing-
block percentage (which is what `margin: auto` and `%`-based `padding`
resolve against) doesn't, and — the one that actually mattered in
practice — the formula had no idea `html.sidebar-pinned` existed, so
once a viewer pinned the sidebar open, main stopped centering
(flush-after-sidebar, not re-centered) while the calc() kept computing
as if it hadn't, drifting further off the wider the window got. Sharing
the actual box model instead of reverse-engineering an equivalent
sidesteps both failure modes at once — there's no formula to keep in
sync with main's if it ever changes.

`.topbar-left`'s own `padding-left` (2.55rem by default, zeroed out via
media query once `.topbar-inner`'s own margin — centering or pinned —
already clears it) exists purely to keep the title clear of the fixed
hamburger button (`.sidebar-toggle`); see the CSS's own comment for the
exact breakpoints, one for each of unpinned/pinned.

### Toggle switch vs checkbox

Settings has both `input[type="checkbox"]` (a hand-drawn square check,
see `style.css`'s "Custom checkbox/radio" comment) and `input[type=
"checkbox"].switch` (a track/thumb pill, same underlying element and
JS — `.switch` is purely `appearance`, no behavior change). Which one a
given boolean gets is a judgment call, not a toggle-switches-everywhere
rule: `.switch` is for a genuine Settings preference, a persistent mode
the *app* is in (Amount entry's fill-direction toggle is the one so
far) — not a data field an entity actually has (Accounts' "leaf"), a
filter over a report/list (Trial Balance's "show zero balances"), a
bulk-selection control (Staging's row checks), or a plain form checkbox
with its own strong convention ("Remember me"). Those answer "what is
this record" or "which rows do I mean"; a checkbox says that. A switch
reads as "which mode is the app in right now," which only Settings
actually holds today.

### The theme picker is a searchable `<select>`, same as everywhere else

Settings > Appearance is a plain `<select id="theme-select">` — no
different from the payee/account/tag pickers elsewhere in the app —
enhanced into a searchable dropdown by `combobox.js`, which every
`<select>` on the page already gets automatically. Typing filters the
22 options by name; the underlying `<select>` still holds the real
value, so `theme.js`'s `change` listener (same `localStorage` key, same
`data-theme` attribute, same pre-paint switch in `base.html`'s `<head>`)
needed no changes to keep working.

This briefly wasn't a `<select>` — a 2026-08-26 pass replaced it with a
grid of color swatch buttons, on the theory that a theme is a palette
and a name alone can't show you what one looks like. Reverted the same
day: search-to-filter turned out to matter more in practice than seeing
swatches up front, and a `<select>` keeps the theme picker consistent
with every other "pick one of many named things" control in the app
instead of being the one field styled differently. Each theme is just a
`:root[data-theme="..."]` block in `style.css` either way — the picker
UI has never been how theming itself works, only how one gets chosen.

**Considered, rejected: one CSS file per theme** (2026-08-26, prompted by
noticing monkeytype.com does this). Worth being precise about what
monkeytype actually does first, since it's not quite "one file per
theme": the real palettes (bg/main/sub/text/error/...) live in one
central `themes.ts` object; `frontend/static/themes/*.css` is a much
smaller, optional set of *extra* per-theme files (`hasCss: true`) for
things a plain palette can't express — Matrix's scanline animation,
Shadow's color-cycling keyframes — not the color definitions themselves.
So the actual prior art here is "one manifest, plus opt-in extras," not
"one file per palette." Splitting this app's `:root[data-theme="..."]`
blocks into 22 separate files was rejected anyway, on this app's own
merits:

- The pre-paint script (`base.html`'s `<head>`, before the stylesheet
  even loads) is what avoids a flash of the wrong theme on load — it
  works today because every theme's CSS is already sitting in the one
  stylesheet the page always loads. Splitting into 22 files only pays
  off (skip loading the 21 themes not in use) if the pre-paint script
  also picks which `<link>` to inject before first paint — real, but
  meaningfully more moving parts than this app's "no build step, hand-
  written CSS" stance (see this doc's own Stack table) asks for, to
  save a few KB no self-hosted single-user install will ever notice.
- Every other kind of styling in this app — components, layout, the
  other patterns on this page — stays in the one `style.css` file by
  deliberate choice; giving only themes a different file-per-item
  convention would be the inconsistent choice, not the tidy one.

If the theme roster keeps growing well past this, the cheaper next step
is splitting `style.css` in two (component CSS / theme palettes) rather
than one-file-per-theme — still one extra request, not twenty-two.

### Opting out of the standard chrome

Every page gets `base.html`'s topbar/main/footer for free — except
Login, which wants a full-bleed split screen instead (brand on the
left, the form on the right; see `.auth-split` in `style.css`). Rather
than a second base template to keep in sync with the first, `base.html`
wraps topbar+main+footer in `{% block chrome %}...{% endblock %}`; a
page that needs something completely different just overrides that
block instead of `{% block content %}`, and still inherits `<head>`
(theme pre-paint script, stylesheet, `<title>`) for free. Login re-does
the two flash-message `{% if %}`s itself since it isn't using `<main>`'s
copy — the one bit of duplication this costs.

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
`form.requestSubmit()` the moment a `<select>`, date/month field, or
checkbox changes (Trial Balance's "show zero balances"/"show true
balances", Balance Sheet's "show true balances"). It's a `change`
listener on the *form*, not on each field, so it needs no re-binding
when combobox.js/datepicker.js swap a plain `<select>`/`<input
type="date">` for their own enhanced markup — both of those already
dispatch a real bubbling `change` on the original element when a value
is picked (see their own files), which is all a bubble-phase listener
on an ancestor ever needed. Deliberately excludes text fields (Search,
the Amount value) and the tag picker: those are typed into, not picked
from, so including them would turn every keystroke into a mid-word
navigation.

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
get a disposable `postwarden_test` database per run (dropped and recreated
from `db/schema.sql` + `db/seed.sql` — no demo data — via
`pytest_configure`).

Run them (from the repo root, with `docker compose up -d db` already
running):

```bash
POSTWARDEN_TEST_ADMIN_URL=postgresql://postwarden:postwarden@localhost:5432/postgres \
POSTWARDEN_TEST_URL=postgresql://postwarden:postwarden@localhost:5432/postwarden_test \
pytest -q
```

See the README's own "Tests" section for the Docker-network variant that
needs no local Postgres client at all.
