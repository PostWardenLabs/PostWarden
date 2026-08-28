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
| Dashboard | `/` | always ACTUAL — "how are my real finances doing," no scenario picker. Recent activity and Upcoming transactions are the same widget shape twice (journal_lines vs. scheduled_entry_lines) — both reuse one `flow_side()` closure to build the "Salary Income → Cash" label, batched per widget the same way (one query for every row's lines rather than N+1) |
| Trial balance | `/trial-balance`, `/export/trial-balance.csv`, `/export/trial-balance.xlsx` | `_build_account_tree`/`_flatten_tree` (defined here) are reused by Balance Sheet, Income Statement, and the Budget grid. Its `.xlsx` export is the first to use the "subtotal"/"grand" row styles added to `_xlsx_data_row` alongside Income Statement's own "group"/"line"/"running" — a bold section-title row per account type, that type's own per-type subtotal row only when it actually has more than one top-level account (`g["show_type_total"]`), and a bottom "In balance"/"Out of balance" row with the accountant's double-rule border, red instead of ink when it doesn't |
| Income statement | `/income-statement`, `/export/income-statement.csv`, `/export/income-statement.xlsx` | the only report with a date *range* (not "as of") and a two-scenario compare column; `_build_account_tree`'s optional `compare_by_id` rolls both scenarios up in one tree, one group per top-level income/expense account (`_income_statement_groups()`) for the waterfall — see the module comment above `_pct_variance`. Its own `split` param (`""`/`monthly`/`quarterly`/`yearly`) turns the single range into a column-per-period matrix — see [Split: multiple periods at once](#split-multiple-periods-at-once). The `.xlsx` export is a styled `openpyxl` rendering of the exact same `_income_statement_rows()`/`_income_statement_matrix()` data the `.csv` export writes — same rows, same figures, just with fonts/fills/borders/frozen panes and account-depth indentation standing in for the CSV's separate Path column. Every cell is a literal, not a formula (see the route's own docstring for why a `SUM()` over a visible row range isn't safe against this tree's rollup); the shared styling constants (`_XLSX_*`) and helpers (`_xlsx_header_row`, `_xlsx_data_row`, `xlsx_response`) live just above `csv_response()` for reuse by any other report's own XLSX export later |
| Balance sheet | `/balance-sheet`, `/export/balance-sheet.csv`, `/export/balance-sheet.xlsx` | its `.xlsx` export uses the same bold section-title + depth-1-root-row-as-total pattern Income Statement's groups use; "Total assets"/"Total liabilities + equity" are a real cross-section identity rather than a duplicate of any row above them, so they keep their own "grand"/"grand_bad" row |
| Cash flow statement | `/cash-flow`, `/export/cash-flow.csv`, `/export/cash-flow.xlsx` | Flat (no operating/investing/financing split — out of scope, SPEC.md decision 20), grouped by contra-account rather than the account-tree rollup every other report here uses. `fn_cash_flow_lines` (`db/schema.sql`) does the real per-transaction attribution at full granularity — every non-cash leg, its own posted amount, sign-flipped, unchanged regardless of how the report above it groups things. `_cash_flow_rows()` (`app/main.py`) is where that grouping happens, per-entry, in three rules (see its own docstring and SPEC.md decision 20's addenda for the full reasoning): an equity-typed contra leg always lands in its own **Ledger adjustments** section, never blended into Inflows/Outflows (opening-balance seeding is real cash movement, but not real economic activity); an entry with exactly one income-typed leg and at least one expense-typed leg collapses into a single row under the income leg's own account, valued at their net, with the folded legs demoted to a `netted_from` annotation rather than deleted (two or more income legs on one entry is left un-netted — no principled way to say which leg a shared deduction belongs to); everything else (asset/liability legs always, any leg the other two rules didn't consume) itemizes exactly as `fn_cash_flow_lines` returned it. None of this changes `net_change`'s own arithmetic — the three rules only ever regroup rows that already summed to the same total — so `_cash_flow_tie_out()`'s three-way check (statement total vs. net cash-account leg activity vs. balance-sheet roll-forward) is unaffected by any of it, and now also returns `beginning`/`ending` balances that the report renders unconditionally (previously computed only for the failure-banner case). A mismatch still renders as a `.flash-warn` banner (same amber "needs a look" treatment as the Dashboard's pending-Staging banner, not a hard error — the report still renders) and logs via the module's one `logger.error()` call. A transaction with more than one cash leg (a payroll deposit split checking/savings) is attributed correctly with no actual ambiguity — see the function's own comment — but still surfaces in a second banner for manual review, per the spec's explicit ask. Date range is inclusive on both ends, same convention as Income Statement, not the half-open range the original feature request described — kept consistent with every other report's own date handling instead. Its `.xlsx` export has no account tree to walk (every row here is already flat, one per contra account), so no depth/indent and no group-row-as-total concern the tree-shaped reports have — Beginning/Net change/Ending get a bold "group" headline row each, and the closing Tie-out row reuses the grand/grand_bad split, green ink for PASS, red for FAIL |
| Budget grid | `/budget`, `/budget/cell` | `_budget_rows()` builds two account-trees (budgeted, actual) and merges them node-for-node — see [the pattern below](#the-account-tree--rollup-pattern) |
| Variance | `/variance`, `/export/variance.csv`, `/export/variance.xlsx` | general two-scenario diff. Two modes: no rollup (native depth) builds a real `_build_account_tree` for chevrons + zero-balances, same as Trial Balance/Balance Sheet/Income Statement; a chosen `account_levels` depth stays on `fn_rollup_balance`'s SQL-side aggregation instead (accounts posted at different native depths reconciled into one row — no tree to walk there, so no chevrons, and the zeros checkbox is a no-op with a tooltip saying so). Its `.xlsx` export is built from `v["grouped"]` rather than the CSV's flat `v["merged"]` list, so it can add section headers, a per-type subtotal (native mode: only when a section has more than one top-level account, same reasoning as Trial Balance; rolled-up mode: always, since no row there is ever "the" section total the way a tree's own root row is), a real % Variance column the CSV omits, and the same red/green conditional-formatting Income Statement's own Variance/% Variance columns use |
| Chart of accounts | `/accounts`, `/accounts/quick-create` | |
| Journal entry create | `/entries` POST | `_parse_lines()` turns the grid's parallel `account[]/debit[]/credit[]` arrays into line dicts |
| Journal browser | `/entries` GET, `/entries/export.csv`, `/entries/export.xlsx`, `/entries/reverse`, `/entries/{id}/reverse`, `/entries/tags`, `/entries/{id}/edit-description` | `_entries_filter()` builds the one WHERE clause the HTML view and both exports share; its date/search/tags/account/payee/amount fragments live in `_shared_journal_filters()`, reused as-is by Staging's own filter bar (`_staging_filter()`) — only Scenario differs between the two (the Journal's own posted scenario vs. Staging's target scenario, since every Staging row already shares one real scenario). `_entries_filter()`'s WHERE clause starts unconditionally with `NOT s.is_staging`, not just "no scenario filter selected" — the Journal never shows a pending Staging entry regardless of filter state, even a hand-edited `scenario=STAGING` query string, and its Scenario `<select>` (Staging-filtered same as the WHERE clause) drops the old "All" option entirely rather than offer a catch-all next to specific scenario codes; ACTUAL sorts first (scenario_type enum order) and is what shows selected on an unfiltered page load. **Select entries** (`entries-select.js`) reveals a checkbox per entry, same mechanism as Staging's bulk Approve/Reject — `/entries/reverse` is the bulk sibling of the single-entry route, both backed by one `_reverse_one_entry()` helper; confirms via `confirm.js`'s `ask()` with a count-aware message before submitting, Alt+R triggers it. The old per-entry "Reverse this entry" button is gone, same consolidation as Staging's Reject. Its outer `<form id="entries-select-form">` wraps only the toolbar, not the entries below it — a `<form>` can't nest inside another one, and each entry gets its own "Edit description" `<form>` — every checkbox still belongs to it via `form="entries-select-form"` (an input can be associated with a form anywhere in the document that way, not just one it's a DOM descendant of) rather than literal nesting. **Edit tags** posts to `/entries/tags` once per chip added/removed (`action=add`/`remove`, one tag, the checked `entry_id`s) — `_add_tag_to_entries()`/`_remove_tag_from_entries()` touch only `journal_entry_tags` (no immutability trigger there — see SPEC.md decision 16), additively, never a full replace like `_sync_entry_tags()` does for a single entry's own tags, since different selected entries can have different existing tags. **Edit description** (inline in each entry's expanded panel, its own small `<form>`) is the one column of an already-posted entry actually editable — same decision 16 reasoning as tags. `/entries/export.xlsx` is a styled counterpart to `export.csv` — same filters, same rows, same DESC-by-date order — but grouped back into entries rather than one flat line per row: each entry's legs are debits-then-credits (not `line_no`'s original posting order), every entry-level column (Entry #, Date, Scenario, Description, Reference, Payee) merged and centered down every leg — written once, on the entry's first leg row, since `merge_cells()` discards whatever's in a merged range's other cells on save regardless — credit legs indented under the debits (account columns and the Credit amount cell alike), and a rule drawn only under an entry's last leg so two legs of the same transaction never show an internal line between them. It doesn't reuse `_xlsx_data_row`'s tree-shaped row model — the per-leg indent only ever applies to two of the eleven columns, and the entry-level columns are merged rather than repeated, neither of which fits that helper's "everything but the first label column" depth convention — but does reuse the shared `_XLSX_*` palette (fonts, money format, grand-total border/coloring, title/subtitle style) so it still reads as one of this app's own exports. Bottom row is a bold Debit/Credit total with the accountant's double-rule, live `SUM()` formulas over the two amount columns (safe here — unlike a tree-shaped report, every row is already a real leaf, so a range sum can't double-count), red instead of ink if a scenario in the filter allows single-sided entries |
| Scenarios | `/scenarios`, `/scenarios/{id}/toggle-lock` | create + lock-toggle only — no edit, no delete (see SCHEMA.md) |
| Account levels | `/account-levels` | |
| Payees | `/payees`, `/payees/quick-create`, `/payees/{id}/toggle-active`, `/payees/{id}/rename`, `/payees/{id}/delete`, `/payees/merge` | quick-create is called via `fetch()` from the New entry payee combobox. Archive/Unarchive (`toggle-active`) only hides a payee from that combobox and the Scheduled/Staging pickers (`WHERE is_active` in each of their own queries) — it never touches history. Delete is a real `DELETE`, safe by construction since every FK onto `payees(id)` (`journal_entries`, `scheduled_entries`, `entry_templates`) is `ON DELETE SET NULL`. Merge folds two or more selected payees into one (`entity-manage.js`'s popup, prefilled with the first selected payee's name, editable before confirming) — the first selected id survives, every other selected payee's FK references get repointed to it (deleting the other rows *before* renaming the survivor, so the typed name can't collide with a row about to be deleted), then the survivor is renamed to whatever was typed. Select/Merge and the inline Edit-in-place rename are both `entity-manage.js` — [see the pattern below](#entity-manager-payees-tags) |
| Tags | `/tags`, `/tags/{id}/toggle-active`, `/tags/{id}/rename`, `/tags/{id}/delete`, `/tags/merge` | A management page for the tag entity itself, not for tagging one entry (that's `tags.js`, on `entries.html`/`scheduled.html`/`entry_templates.html`) — same shape as Payees (`entity-manage.js` again), including Archive/Unarchive: `all_tags()` (the tag-input's own suggestion source) filters `WHERE is_active`, and `_sync_tags()`/`_add_tag_to_entries()` both reactivate on `ON CONFLICT` the same way `quick_create_payee` does, so typing an archived tag's name while tagging something is exactly the "back in use" signal it already is for payees. Merge dedupes across three many-to-many junction tables (`journal_entry_tags`, `scheduled_entry_tags`, `entry_template_tags`) instead of one FK column — each gets an "insert the survivor's own association wherever a merged-away tag had one, `ON CONFLICT DO NOTHING`" pass before the old tag rows are deleted, since a plain `UPDATE ... SET tag_id` could collide with a row that already exists (something tagged with *both* the survivor and a tag being folded into it) and violate the junction table's own primary key |
| Scheduled entries | `/scheduled` | `materialize_due_schedules()` runs lazily on request (no cron in this deployment), posting each due occurrence into Staging |
| Staging | `/staging`, `/staging/approve`, `/staging/reject`, `/staging/{id}/edit` (GET: JSON data, POST: save), `/staging/{id}/reject` | review/approve page for whatever's sitting in the one `is_staging` scenario, filterable by the same fields as the Journal (see the row above) — checkboxes + "Approve" (Alt+A) copies each into its real target scenario and sets `promoted_entry_id`. The top-of-page **Reject** button (Alt+R) is the only UI path to rejecting now — one entry checked or many, same checkboxes Approve uses — calling `/staging/reject`, its own bulk permanent-delete loop mirroring Approve's; `/staging/{id}/reject` (singular) still exists underneath and is still fully tested, just with no button pointing at it anymore since the bulk route already covers a single id. `pending_staging_entries()` is the shared query the Dashboard's banner count also uses (called with no filter args there). Per-entry **Edit** opens inline (see `staging-inline-edit.js`/`app.js` below) — a trimmed-down New-entry grid, one fixed target scenario instead of a picker, everything else the same `app.js`/`combobox.js`/`datepicker.js` machinery — rather than navigating to a separate page; `GET /staging/{id}/edit` is what it fetches for that entry's own data, `POST` to the same path is unchanged from before (still redirects back to `/staging` on success). Edit and both Reject routes only work on a still-pending entry — see SPEC.md decision 15 for why that's even possible given decision 4's append-only rule |
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
`theme.js`, `font.js`, `cents-entry.js`, `money-format.js`, `date-format.js`, `auto-refresh.js`,
`confirm.js`.
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
| `app.js` | The journal-entry line grid, shared by New entry, Scheduled, Entry templates, and Staging's inline Edit panel — keyboard flow (Tab moves account → debit → credit → memo → next row; Enter/Shift+Enter move vertically instead, same column, next/previous row, overriding a plain text input's default of submitting the form), live balance bar, fetch-based submit so a rejected entry doesn't lose what you typed, and Distribute (fills whichever line has focus with whatever amount, on whichever side, zeroes the entry out — always overwrites that line rather than adding to it). Global shortcuts via `e.code` rather than `e.key` (Option+letter types an accented character on a Mac, so `e.key` never matches there): Alt+N adds a line, Alt+D triggers Distribute, Alt+E toggles New entry's `<details>` open/closed, focusing the first line on open (Journal page only). Clear (Journal only, no keyboard shortcut on purpose — see entries.html's own comment on why) resets every field back to its page-load default: description/reference/tags empty, payee unset, date/scenario back to their original `defaultValue`/`selectedIndex`, grid back to two blank rows — same shape as `entry_templates.js`'s "Load template" (loading the blank template, in effect). |
| `auto-refresh.js` | Every `<form class="bar" method="get">` — a delegated `change` listener submits the form the moment a `<select>`, date/month field, checkbox, or the tag picker's hidden value field changes (tags.js dispatches `change` on it exactly once per add/remove, not per keystroke) — so a report or the Journal's filters refresh without a separate button. Free-typed text (Search, Amount) stays out of this on purpose; Search has its own submit icon, Amount just needs Enter. |
| `budget-grid.js` | The Budget grid's editable cells — live client-side subtotal recompute plus per-cell autosave on blur. |
| `combobox.js` | Every `<select>` on the page, into a searchable/filterable dropdown. |
| `confirm.js` | Replaces the browser's own `confirm()` with a styled modal matching the app (`window.PostWardenConfirm.ask(message, opts) → Promise<boolean>`). Also wires up `<form data-confirm="...">` / `<button data-confirm="...">` generically: intercepts the submit, awaits the modal, and — only if confirmed — resubmits via `form.requestSubmit(submitter)` (preserves a button's own `formaction`/`formmethod` override, if it has one). A message computed at click time (Staging's "Approve N entries" and its bulk Reject) calls `ask()` directly instead of using the attribute — see `staging.js`. `opts.danger` renders OK in red, reserved for something that actually deletes data (Delete template/level, Reject); Reverse and Approve stay the default color. |
| `datepicker.js` | Every `<input type="date">`, into a calendar popup (still submits a plain `YYYY-MM-DD`) — arrow keys/Home/End/PageUp/PageDown move around the open grid via a roving tabindex (one day is ever a real Tab stop; the rest are reachable by arrow key but not by Tab), closes on Escape or on focus actually leaving the whole widget (checked a tick after focusout, not from its relatedTarget — re-rendering the grid on every move destroys the old focused button first, which fires focusout with no relatedTarget yet). |
| `number-stepper.js` | Every `<input type="number">` (Account levels' Depth, Scheduled's "Repeats every") — hides the browser's native spinner and adds the site's own chevron up/down buttons; typing and the keyboard's own arrow keys still work, input stays `type="number"` throughout. |
| `tags.js` | The tag chip input (select-or-create, comma-separated hidden value underneath). |
| `entry_templates.js` | "Load template" on New entry — fills the grid client-side from a page-embedded JSON blob. |
| `import-file.js` | Import's CSV file field — proxies the visible "Choose file" button's click to the real (`.sr-only`) `<input type="file">`, and keeps the visible name box in sync with whatever's actually chosen (or the placeholder, if the picker was cancelled with nothing selected). |
| `entries-select.js` | The Journal's "Select entries" mode — toggles a checkbox per entry and the bulk Reverse/Edit tags buttons (`.select-only` in style.css, hidden until toggled on), same select-all/disabled-until-checked/count-aware-confirm shape as `staging.js`'s Approve/Reject. Alt+R clicks Reverse. Edit tags opens a popup built from confirm.js's own `.confirm-overlay`/`.confirm-modal` CSS (same look, no `ask()` call — this one holds an "Edit Tags" `<h3>` and `tags.js`'s pill box instead of a message and buttons, plus a lower-left Done button in a `.confirm-actions` row that just closes the popup, since there's nothing to save behind it) prefilled with the union of tags across whatever's checked; each chip add/remove diffs against that starting set and fires `/entries/tags` immediately, no Save button to batch behind. Closing the popup (Escape or the backdrop) reloads the page if anything actually changed, since the tag badges next to each entry are server-rendered. Queries checkboxes document-wide (`document.querySelectorAll(".entry-check")`), not scoped to the form — they're associated with it via `form=""` (see the Journal browser row above), not DOM nesting, so `form.querySelectorAll(...)` would never find them. |
| `entity-manage.js` | Payees and Tags' shared page script (`payees.html`/`tags.html`) — one file for both rather than two near-identical ones, since the two entities differ only in route/label, not interaction. Select mode reuses `entries-select.js`'s exact `body.select-mode`/`.select-only` mechanism, just over `<td>`s instead of a details-summary gutter. Merge (enabled at 2+ checked) opens a popup built the same way `entries-select.js`'s Edit tags does (confirm.js's own `.confirm-overlay`/`.confirm-modal` CSS), holding a text field pre-filled with the first checked row's name — but unlike Edit tags' live-diffing fetches, confirming here fills in the page's own hidden `#merge-form` (one hidden input per checked id, plus the typed name) and does a real `form.requestSubmit()`, since a merge is one atomic action with one flash-redirect result, not a stream of small edits. Edit swaps a row's name `<span>` for its own small `<form>` in place (a real `<input>`, not a popup) — Enter submits it natively (a single-text-field form's standard implicit-submission behavior, no JS needed for that part), Escape reverts without saving. |
| `cents-entry.js` | Optional "digits fill in from the right" amount entry (POS-terminal style), toggled in Settings. |
| `accounts.js` | The Chart of Accounts page's collapsible tree, plus its inline "+" add-category form. |
| `report-tree.js` | The same collapse/expand interaction, reused on Trial Balance/Balance Sheet/Income Statement/Budget grid — smaller than `accounts.js` since reports don't need the add-category form. Defaults *expanded* (reports are for reading numbers); Accounts defaults *collapsed* (browsing structure). |
| `period-picker.js` | The date-range preset dropdown on Income Statement — fills in the two real `date_from`/`date_to` inputs; the backend never sees the preset itself. |
| `money-format.js` | Rewrites every `{{ x | money }}` span's displayed text using the symbol/decimal/thousands preference saved in Settings. Also exposed as `window.PostWardenMoney.format()` for the handful of places (the New entry balance bar, `budget-grid.js`) that compute a total client-side and need the same formatting without a `{{ }}` span to rewrite. |
| `date-format.js` | Same pattern, one filter over: rewrites every `{{ x | dateformat }}` span (Dashboard's Recent activity, Journal, Staging, Scheduled's Next date) using the format saved in Settings — ISO/US/EU/long. Parses the ISO string by hand rather than `new Date(...)`, which would parse as UTC and can shift the displayed day in a timezone behind UTC; every date here is a plain DATE column, so this only ever reorders y/m/d. |
| `sidebar.js` | Hover-to-preview / click-to-pin hamburger nav. |
| `staging.js` | The Staging page — "select all" toggles every entry checkbox; Approve and the bulk Reject button both stay disabled until at least one is checked, and both confirm via `confirm.js`'s `ask()` (count-aware message, so it can't be a static `data-confirm` — the check for that attribute on `e.submitter` is what tells this listener apart from a hypothetical future button that confirms itself the ordinary way). Alt+A clicks Approve, Alt+R clicks Reject. |
| `staging-inline-edit.js` | Staging's "Edit" — relocates one shared `app.js` grid panel (`#staging-edit-panel`, parked hidden next to `#staging-edit-panel-home` when nothing's open) into whichever pending entry's own `.lines` div was just clicked, in place of navigating to a separate page. Fetches that entry's own data from `GET /staging/{id}/edit` (a JSON endpoint now, not a page) and fills the panel in — description/reference/payee/tags fields directly, the grid via `PostWardenEntryGrid.setAccounts()` + `clear()` + `addRow()` per line, same shape `entry_templates.js`'s "Load template" uses. Only one entry can be mid-edit at a time (one grid on the page); opening a second one closes whichever was already open first, restoring that entry's read-only view. Save (`app.js`'s own submit handler, unchanged) still does a real redirect back to `/staging` — this only removes the navigation it used to take just to *open* an entry for editing. |
| `theme.js` | The theme `<select>` in Settings; the pre-paint switch itself lives inline in `base.html`. |
| `font.js` | The font-bundle `<select>` in Settings — same shape as `theme.js` (own `localStorage` key `postwarden-font`, own `data-font` attribute, own pre-paint switch in `base.html`'s `<head>`), a deliberately separate, independent choice from Theme. Picks one of a handful of named bundles (System/Classic Serif/Modern Sans/Monospace), each overriding some subset of `--serif`/`--sans`/`--mono` in `style.css`'s `:root[data-font="..."]` blocks — never a single free-text typeface. Classic Serif also repoints `--figures` (see below) at `--serif`, which is what actually renders ledger numbers in serif rather than the app's usual monospace figures. |

## Patterns used more than once

Rather than re-explain these at every call site, here's each one, once.

### The account-tree / rollup pattern

Trial Balance, Balance Sheet, Income Statement, Variance (at native
depth — see its own route table entry above for the rolled-up case),
and the Budget grid all show the same kind of thing: a hierarchical
chart of accounts where a summary account (e.g. "Current Assets") needs
to display the *sum* of everything under it, not just its own direct
postings, and the whole thing needs to collapse/expand.

- **Server side** (`app/main.py`): `_build_account_tree(accounts,
  balances_by_id, compare_by_id=None)` takes the flat account list (from
  `v_dim_account`) and a `{account_id: balance}` map, builds the
  parent/child forest, and rolls each node's `subtotal` up from its own
  balance plus every descendant's. The optional second map rolls up
  alongside the first into `compare_subtotal` — Income Statement's own
  second-scenario column, so one tree drives both a plain report and a
  two-scenario comparison; ordinary callers that pass nothing get
  `compare_subtotal` fixed at 0 on every node. `_flatten_tree(nodes,
  zeros)` walks it depth-first for template rendering, dropping a
  subtree whose `subtotal` *and* `compare_subtotal` are both zero unless
  `zeros` (that "and" is what makes the parameter a no-op for callers
  with no compare map — `compare_subtotal` is already always 0 there).
  The Budget grid needs *two* numbers per node too (Budgeted and
  Actual), but merges them differently — `_budget_rows()` calls
  `_build_account_tree` twice, once per side, and merges the two trees
  node-for-node, since Budget always shows every account regardless of
  either side being zero (it's an entry form, not a report) rather than
  hiding anything. Income Statement's `_income_statement_groups()`
  builds one group per top-level income/expense account (its own
  waterfall — see the module comment above `_pct_variance`), each
  group's rows being that root's own `_flatten_tree([root], zeros)` —
  the root itself is a normal (possibly collapsible) row opening the
  group, not just implied by the header text above it.
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

### The `pct_of_base` variance-convention toggle

Income Statement, Variance, and Budget Grid all show a % variance
column, and all three share one "Flip variance direction" checkbox (next
to Hide zero balances, or on its own in Budget Grid's filter bar, which
has no zeros checkbox) that swaps which of the two figures being
compared plays "new" vs. "old" in the underlying percent-change reading
— flipping the numerator direction *and* which figure is the
denominator together, not just the sign.

- **Server side**: `_pct_variance(base, compare_val, pct_of_base=False)`
  and its dollar-figure counterpart `_variance_amount(base, compare_val,
  pct_of_base=False)` are the one shared implementation — the standard
  `(new - old) / old` percent-change formula. Default (unchecked):
  `base` plays "new," `compare_val` plays "old" — `(base - compare_val)
  / abs(compare_val)`. Checked: the two swap roles — `(compare_val -
  base) / abs(base)`. Every call site passes `base` = that report's own
  primary figure and `compare_val` = whatever it's measured against, in
  the *same* positional order everywhere — Income Statement's `scenario`
  then `compare`, Variance's `baseline` then `compare`, Budget Grid's
  `actual` then `budgeted` — a deliberate uniformity: an earlier version
  of Variance passed these two in the opposite order from the other two
  reports (baseline second, meant to always land in the denominator
  position regardless of checkbox state) — a real, intentional design
  choice at the time, not a bug, but one this session's own explicit
  request revised in favor of one consistent rule everywhere: `base` is
  always this report's own primary figure, full stop, and each route
  reads `pct_of_base: int = 0` from the query string and threads it
  through to `_income_statement_rows()`/`_compute_variance()`/
  `_budget_rows()` and on to every level (row, subtotal, grand total)
  that computes a variance.
- **Markup**: a plain `<label class="checkline"><input type="checkbox"
  name="pct_of_base" value="1" ...>` inside the report's own `form.bar`
  (or `form[data-auto-refresh]` — see auto-refresh.js), same as `zeros`
  — no dedicated JS needed for the checkbox itself, auto-refresh.js's
  existing delegated `change` listener already resubmits on any checkbox
  inside a covered form. Income Statement hides the checkbox entirely
  when there's no `compare` scenario picked (`{% if compare %}`), since
  there's no variance concept to toggle without one; Variance and Budget
  Grid always have both sides, so theirs is unconditional. Every
  Export CSV/XLSX link and Budget Grid's month prev/next links carry
  `pct_of_base` forward so it survives navigation, same treatment every
  other filter already gets. The query parameter itself keeps its
  original name (`pct_of_base`) even though "of base" no longer quite
  describes the new formula — renaming a public, bookmarkable query
  string wasn't worth it for what's ultimately an internal identifier;
  only the checkbox's own visible label changed.
- **Budget Grid's client side**: `budget-grid.js` reads the toggle once
  from a `data-pct-of-base` attribute the template stamps onto the
  `<table>` (server-rendered from the same query param) and mirrors both
  formulas in JS, so typing into a Budgeted cell recomputes Variance/%
  variance live using whichever convention the page loaded with —
  Actual never changes client-side, so there's nothing to keep the
  toggle itself in sync with; only a full page reload (the checkbox's
  own auto-refresh) ever changes which formula is live.

### Split: multiple periods at once

Income Statement's `split` query param (`""`/`monthly`/`quarterly`/
`yearly`, a `<select name="split">` next to Period) turns the report
from one date range into a matrix — one column group per calendar
period instead of one for the whole range. Scoped to Income Statement
only: it's the only report built around a date *range* to begin with —
Variance takes a single `as_of` date (a snapshot, like Balance Sheet)
and Budget Grid already steps one calendar month at a time via its own
prev/next links, so neither has a range to split without a separate
redesign of its own filter model first.

- **`_split_periods(date_from, date_to, split)`** turns the range into a
  list of `{label, date_from, date_to, partial}` dicts — real calendar
  months/quarters/years (`date_trunc`-style boundaries computed in
  Python, not even day-slicing), each **clipped** to the requested range
  at both ends rather than expanded outward to a whole calendar period:
  a custom range of Aug 15–Oct 3 split quarterly produces a Q3 column
  covering only Aug 15–Sep 30 and a Q4 column covering only Oct 1–3,
  `partial=True` on both, rather than silently pulling in days outside
  what date_from/date_to actually asked for. The template marks a
  partial period's label with a `<sup>*</sup>` and shows one shared
  footnote below the table explaining it, rather than a parenthetical
  date range inline on every such header (an earlier cut of this that
  read as more confusing than informative). Returns `[]` — the same
  "nothing to do" signal `compare=""` already is elsewhere — for an
  unrecognized/empty `split`, an inverted range, or (income-statement-
  export-csv only, since that route doesn't default blank dates to this
  month the way the page route does) an empty date_from/date_to; capped
  at 60 periods as a sanity limit, not a real one.
- **`_income_statement_matrix(scenario, periods, date_from, date_to,
  compare, zeros, pct_of_base)`** is the split-view counterpart to
  `_income_statement_rows()`, built as a thin wrapper around that same
  single-period function rather than a parallel calculation. Every real
  period gets its own full `_income_statement_rows()` call with `zeros`
  forced on, which guarantees every account row/group exists in every
  period aligned by account id — a plain lookup merge from there, with
  no risk of August ending up with a different set of rows than
  September because one had a zero-balance account the other didn't. A
  separate "combined activity" tree (the same `_build_account_tree`/
  `_income_statement_groups` machinery the single-period report already
  uses, fed the sum of `|base_net|`/`|compare_net|` across every *real*
  period) decides which rows/groups actually render under the *real*
  `zeros` flag — a row shows if it had activity in *any* period, hiding
  only if it was zero everywhere, the same meaning "show zero balances"
  already has, just extended across the whole matrix. Each surviving
  row/group then gets its real per-period figures overlaid via a
  `periods` list, keyed by account id (a group's own id is its root
  account's, `rows[0]`) — matched within its own income/expense list
  specifically, not a combined search across both, since nothing stops
  two top-level accounts of different types sharing a name.
- **The trailing Totals and Average columns**: Totals is one more
  whole-range `_income_statement_rows()` call (`date_from`/`date_to`,
  not any one period's own bounds), appended to `periods`/
  `periods_totals` *after* the zero-activity union check above — it
  only ever restates rows the real periods already decided to show, so
  it never gets a vote in that check itself (redundant at best, an
  unnecessary second source of truth at worst). Average follows right
  after it: `_scale_income_statement_result(totals_result, len(periods))`
  divides every dollar figure in Totals' own result by the real period
  count and carries every percentage/ratio field through unchanged — a
  plain division is *exact* here, not an approximation, because Split's
  periods partition the date range with no overlap or gap (so
  Totals.base_net already equals the sum of every period's own
  base_net) and every percentage field is a ratio of two such amounts,
  which stays identical whether or not both sides get divided by the
  same n. Because both are just one more entry each in `periods`, the
  template's own `{% for p in periods %}` renders them with zero
  special casing anywhere in the row/subtotal/net-income markup — only
  the period-label header needs to know which is which (see next
  bullet). Totals' default label is the plain, JS-free-safe "Total";
  `period-picker.js` rewrites a `#totals-period-label` span client-side
  to match whatever the Period dropdown currently reads ("This
  Quarter", "Custom range", ...) on load and on every change, since the
  backend itself never learns which preset (if any) was picked, only
  the date_from/date_to it resolved to (see that script's own comment —
  a deliberate, pre-existing boundary this doesn't cross). CSV export
  has no such client-side rewrite to lean on, so it always reads the
  plain "Total". Average's own label is always the static "Average" —
  it doesn't map onto a Period-dropdown preset the way Totals does, so
  there's nothing for period-picker.js to rewrite it to.
- **Template**: `income_statement.html` branches on whether `periods` is
  set — the unsplit branch is the original single-range table, byte-for-
  byte the same markup as before Split existed. The split branch mirrors
  it almost line for line, with an extra `{% for p in periods %}` wrapped
  around each column group and a two-row `<thead>` (period labels
  spanning 1 or 4 columns, then the repeated sub-column labels
  underneath) instead of one. The period-label row is centered
  (`.period-label`, overriding `.num`'s own right-align by source order —
  same specificity, later rule wins) rather than right-aligned like a
  plain numeric header, since it spans every sub-column beneath it
  instead of heading just one. Two classes get recomputed identically in
  every `{% for p in periods %}` (Jinja has no shared closure across
  separate loops, so both are deliberately repeated rather than factored
  out):
  - `col_cls`, on a period's *leftmost* sub-column only — `.period-start`
    (a `var(--rule-strong)` left rule, not `.money-first`'s red one) for
    every period after the first, the vertical divider between one
    period's columns and the next, including before Totals and before
    Average — computed once as `multi_period = periods | length > 1`
    (which Totals+Average being always-present means is true the moment
    there's at least one real period, so a single-period split still
    gets dividers before its own Total/Average columns). With only one
    column group total there's nothing to divide from, so no divider
    renders.
  - `agg_cls`, on *every* sub-column of a period (not just the
    leftmost) — `.period-agg` (bold, plus a `color-mix(in srgb,
    var(--rule-strong) 22%, var(--paper-deep))` tint richer than the
    plain `.money` background) marks Totals and Average as aggregates
    rather than a real period's own figures; `.period-agg-average`
    layers italic on top for Average specifically (applied instead of,
    never alongside, `.period-agg`), so the two aggregate columns stay
    visually distinguishable from *each other*, not just from the real
    periods. Both colors derive from existing theme tokens via
    `color-mix()` rather than a fixed value, so they stay correct across
    all 22 themes and dark mode with no per-theme override needed.

  Wrapped in its own `.table-scroll` (`overflow-x: auto`) — a year split
  monthly with a compare scenario is 12 × 4 = 48 data columns (20 more
  with Totals/Average), easily wider than even `main` can stretch to on
  the widest realistic monitor (`main` relaxes its own default width cap
  for any page holding a `.report-table` — see "Report tables size to
  their own content" below — but that's "as wide as the viewport
  allows," not unlimited), and without a scoped scroll container the
  whole page would scroll sideways along with it, dragging the sidebar
  out of view. Every other `table.ledger` stays a handful of fixed
  columns that never approaches this regardless of window size, so only
  this one table gets the wrapper.
- **CSV export** (`/export/income-statement.csv?split=...`) gets its own
  wide-format branch for the same reason a two-row HTML `<thead>`
  wouldn't survive a CSV round trip: one row per account, one column per
  period × sub-column (the trailing Totals and Average columns included,
  same as the HTML table), headers prefixed with the period label
  (`"2026-08 ACTUAL"`, `"2026-08 Variance"`, ..., `"Total ACTUAL"`,
  `"Average ACTUAL"`) so a plain spreadsheet import stays legible with no
  merged header to reconstruct — no bold/italic/tint to carry over, of
  course, since a CSV cell has no such thing.
- **money() normalizes negative zero**: a flipped-sign zero-balance
  income row (`_income_statement_groups`' own `sign = -1 if flip else
  1`, applied to a literal 0) is a genuine Decimal/float negative zero,
  which `%.2f`-style formatting renders as a confusing `"-0.00"`.
  Pre-existing, but Split's internal `zeros=1` (forced on every
  per-period call, to keep rows aligned — see above) surfaces far more
  zero-balance rows than the single-range report normally shows, so it
  came up here first. Fixed at both ends: `_income_statement_groups`'
  own `signed()` helper normalizes it at the source (covers the CSV
  export, which writes raw figures with no formatting rescue), and
  `money()` itself guards independently too (covers `data-value`
  attributes and any other direct caller).

### Click an amount → filtered Journal, with a back link

Income Statement, Balance Sheet, Trial Balance, Cash Flow, and Payees
all link a number through to the Journal filtered to exactly what
produced it, with a way back.

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
horizontal padding).

`.topbar-inner` (wrapping `.topbar-left`/`.topbar-right`) used to mirror
`main`'s own `max-width`/`margin: auto` box model exactly, on the theory
that the title should line up with the page content beneath it — see
this file's own git history for that version and why it was correct at
the time. It stopped being correct once `main`'s own width became
variable per page (see "Report tables size to their own content"
below): matching `main` would mean `.topbar-right` (username/log out)
sits a different distance from the true right edge depending on what
that specific page's content needs, which reads as "stuck in the
middle" on any page whose `main` doesn't need the full width — the
original complaint this whole area of the CSS exists to fix, just
recurring under a new trigger. So `.topbar-inner` is independent of
`main` entirely now: no `max-width`, no `margin: auto`, just
`padding: 0 1.25rem` — a plain block box, full-width by default (an
auto-width block fills its containing block), so `.topbar-right` sits
near the real right edge on every page, on every monitor, regardless of
what `main` is doing. `html.sidebar-pinned .topbar-inner` still gets
`margin-left: 14rem` same as `main`/`.footer` — with no explicit
`width` set, a block box's `width: auto` absorbs a margin rather than
overflowing past its container, so this still works with no `calc()`
needed. `.topbar-left`'s own `padding-left` (2.55rem, clearing the
fixed hamburger button) is now needed *unconditionally* when unpinned
(no media query — there's no viewport width any more at which
`.topbar-inner` naturally clears the button on its own, since it's
always flush left) and zeroed only when pinned, where the sidebar's own
opaque background covers that spot regardless.

An earlier version of the "match main's box model instead of computing
an equivalent" idea is worth remembering even though `.topbar-inner` has
since moved past needing it: a version before *that* tried to
*approximate* `main`'s centering with a `calc()` on `.topbar-left`
instead of sharing `main`'s own properties, and got it wrong two ways at
once — `100vw` includes the scrollbar where a real containing-block
percentage doesn't, and the formula had no idea `html.sidebar-pinned`
existed, so it drifted further off the wider the window got once a
viewer pinned the sidebar. The lesson (share the real thing, don't
reverse-engineer an equivalent) is why `.topbar-inner` today shares
`main`/`.footer`'s pinned-margin behavior exactly rather than
approximating *that* too, even though it no longer shares their width.

### Report tables size to their own content

`main`'s default `max-width` is `var(--content-max)`
(`min(90vw, 1680px)`, shared with `.footer`) — fluid so a wide or
ultrawide monitor gets used, capped so prose and forms don't stretch
into unreadably long lines on a very wide (5120px+) display. That's the
right default for every page *except* a report whose column count the
viewer controls (Balance Sheet, Income Statement — both its no-split
and Split views, Cash Flow, Trial Balance, Variance, Budget Grid): a
fixed cap means a report with only a handful of columns gets stretched
across it regardless (numbers spaced out, harder to scan across — the
opposite of legible), while a report the viewer has genuinely widened
(Income Statement's Split view, a full year monthly) hits the cap and
falls back to `.table-scroll`'s horizontal scroll well before the
screen itself ran out of room.

Two rules, marked by one class (`.report-table`, added to exactly those
report tables' `<table class="ledger ...">` tags — not
`table.entry-grid`, which deliberately keeps `width: 100%` since an
editable grid's input fields need the room a read-only report doesn't):

1. `table.ledger.report-table { width: auto; }` — overrides
   `table.ledger`'s own `width: 100%`, so the table sizes to its actual
   content (`table-layout: auto`, the browser default, already does
   this once nothing forces `width: 100%`) instead of stretching to
   fill `main`.
2. `main:has(table.report-table) { max-width: none; }` — relaxes
   `main`'s cap on exactly the pages that might need it.

These don't fight each other: rule 2 gives a report page's `main` more
width to *offer*, but rule 1 means a table only actually uses it if its
own content needs it — a 3-column Cash Flow report on a page with
`max-width: none` still renders at its own natural (narrow) width, it
just isn't being forced wider by a container cap that no longer applies
to it. There's no per-page "wide" flag or JS column count involved;
`:has()` reads the fact directly off the table that's already there.

A report table sizing itself independently of `main` created a second
problem: each report's Export CSV/XLSX links used to live in a flex row
that spanned the *filter form's* width (effectively `main`'s width), so
once `main` could be wider than a narrow report's own table, the export
links drifted out to the right of the table they belong to — the same
"reads as disconnected from what it's labeling" complaint the topbar
fix above addresses for `.topbar-right`, just recurring one level down.
`.report-frame` (a plain `<div>` wrapping just the Export links —
`.report-export`, a `<p class="bar report-export">` — together with the
table or `.table-scroll` beneath them, added around each of the six
`.report-table` templates) fixes it the same way `main`/`.footer`
already size themselves: `width: fit-content; max-width: 100%`. A block
child (`.report-export`) fills its parent's width by default, so once
`.report-frame` itself shrinks to the table's actual width, right-
aligning the export links within `.report-export` (`justify-content:
flex-end`, inherited from `.bar`) lands them exactly above the table's
own upper-right corner — not `main`'s. For Income Statement's Split
view, `.report-frame`'s `fit-content` sees straight through
`.table-scroll`'s `overflow-x: auto` to the *table's* true (unclamped)
max-content size, which is still whatever the split has grown to; when
that exceeds the available width, `fit-content` clamps back down to it
exactly like it always did, so `.table-scroll` still fills the
available width and still scrolls — this case isn't a special branch,
it falls out of the same one CSS rule. Every filter-only control (the
scenario/date fields, "show zero balances" and similar checkboxes)
stays inside `<form>`, outside `.report-frame` entirely — only the
export links needed this, not the filters.

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

Every report's filter form and the Journal's are a plain GET
(`method="get"`), so the current filters are always a
bookmarkable/shareable URL, no client-side state involved. Staging is
the only one still a single-row `<form class="bar">`; every other
filter form (Journal, Balance Sheet, Trial Balance, Income Statement,
Variance, Budget Grid) has a second row below its fields — a checkbox,
Export CSV, Budget Grid's Go/prev-next — so those wrap their fields in
a nested `<div class="bar">` and carry `data-auto-refresh` on the
`<form>` itself instead of `class="bar"` (putting `.bar` on the form
too would flex its own children — the fields div and the second row —
side by side instead of stacking them; see auto-refresh.js's own
comment). `auto-refresh.js` is one delegated `change` listener per such
form (found by `form.bar, form[data-auto-refresh]`, no opt-in markup
needed on individual fields) that calls `form.requestSubmit()` the
moment a `<select>`, date/month field, or checkbox changes (Trial
Balance's "show zero balances"/"show true balances", Balance Sheet's
"show true balances"). It's a `change` listener on the *form*, not on
each field, so it needs no re-binding when combobox.js/datepicker.js
swap a plain `<select>`/`<input type="date">` for their own enhanced
markup — both of those already dispatch a real bubbling `change` on the
original element when a value is picked (see their own files), which is
all a bubble-phase listener on an ancestor ever needed. Deliberately
excludes text fields (Search, the Amount value) and the tag picker:
those are typed into, not picked from, so including them would turn
every keystroke into a mid-word navigation.

### Flash messages

`flash_redirect(url, ok=, err=)` / `flash_url(...)` append `?ok=...` or
`?err=...` to a redirect target; `base.html` renders whichever is
present as a banner. Stateless on purpose — no session-stored flash
queue to forget to clear.

A third banner color, `.flash-warn` (amber), exists in `style.css` but
isn't wired into `flash_redirect`/`base.html`'s `ok=`/`err=` mechanism —
there's no `warn=` query param. It's used exactly once, hand-coded
directly in the two templates that need it (`dashboard.html`,
`scheduled.html`, both `<div class="flash flash-warn">`) for "N entries
waiting in Staging for your approval": not a success (nothing finished)
and not an error (nothing failed), just a pending state asking for
attention — green or red would both say the wrong thing. A route that
ever needs the same "pending, not done, not failed" distinction through
`flash_redirect` would need a real `warn=` param added there and to
`base.html`'s render block; nothing currently does.

### Entity manager (Payees, Tags)

`payees.html`/`tags.html` share one shape and one script
(`entity-manage.js` — see its own catalog entry above): a Select/Merge
bar, a `<table class="entity-table">` with a `select-only` checkbox
column, and per-row Edit (rename in place), Archive/Unarchive, and
Delete — identical on both pages now (see the Payees route table row
above for why Delete needed Archive kept alongside it rather than
replacing it; the same reasoning applies to Tags).
`details.entry-new.quiet` is the "+ Add payee"/"+ Add tag" bar —
`.entry-new`'s own dashed-box/details-summary shape (same as
the Journal's "+ New entry"), with `.quiet` dropping the `--accent`
color: New entry's bar leads into a whole multi-line grid and earns the
attention accent draws, this one leads into a single text field and
reads better as a plain, secondary affordance.

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
