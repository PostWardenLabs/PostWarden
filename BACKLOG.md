_Hi Claude: This backlog contains features I might want to implement, some are more likely than others (I am particularly unsure of features that could alter the accounting philosophy of the project). Implementing some of these features would affect the database schema, so if I were to start my own PostWarden instance before implementing them they would require a full rebuild and loss of my data. I want you to analyze each feature and tell me which ones would provoke this effect, requiring me to wipe data and rebuild the database (If I were to have a personal instance right now, which I currently don't). I also want you to tell me what you think of these features, which ones are good ideas, which aren't, how you would tweak them._

---

# PostWarden Backlog

## Done

- **Schema audit** — went column by column against actual usage in
  `app/`, `app/templates/`, `app/static/`, `db/seed.sql`, and `tests/`.
  Found one genuinely dead column: `accounts.description` — never
  inserted (not in either account-creation route's own INSERT), never
  selected by any view/report, no form field anywhere, not even in
  `db/seed.sql`'s own starter chart. Dropped it directly in
  `db/schema.sql` (commit `ed5a3ec`). `scenarios.notes` turned out to
  be write-only (the New Scenario form captures it, nothing ever
  displays it back) — not dead, just a small UI gap; flagged, not
  fixed here. Cash Flow Statement's own schema footprint checked
  separately, per your specific ask — it only ever added
  `accounts.is_cashflow` (SPEC.md decision 20), nothing to clean up
  there. `accounts.currency` was left alone at first (unused, but for
  a documented forward-looking reason) — dropped in a follow-up once
  you called out that a per-*account* currency was the wrong shape to
  begin with; if multi-currency ever ships, it belongs on
  `journal_entries` instead. See SPEC.md's Extension roadmap and the
  Multicurrency item below, which already says the same thing.
- **Export the journal to XLSX** — shipped as `/entries/export.xlsx`,
  same filters/rows/order as the existing Export CSV, styled per your
  spec: debits before credits within each entry, credit legs (account
  and amount both) indented under the debits, Entry # merged and
  centered down every leg, a rule between transactions but never
  between two legs of the same one, a title with the scenario/date
  range, no view gridlines, and a bold double-ruled Debit/Credit total
  at the bottom. `v0.24.0`.
- **Journal XLSX follow-ups** — Date/Scenario/Description/Reference/
  Payee now merge and center down every leg the same way Entry # always
  did, written once per entry instead of repeated-then-discarded
  (`v0.24.1`). Separately, traced "why does the export always say All
  scenarios regardless of the Scenario combo box" back to the Journal's
  own filter bar, not the export: the dropdown faked ACTUAL as selected
  on an unfiltered page load (sorts first) while the page was actually
  showing every non-staging scenario mixed together — fixed with a real
  `All` option that's genuinely selected when the filter is blank
  (`v0.24.2`).
- **Excel tweak: Period total/Average formatting** — both columns now
  get the same bold-plus-tint treatment the HTML report's own
  `.period-agg`/`.period-agg-average` already had (Average in italic
  too), so they stand out from a real period in the downloaded workbook
  the same way they do on screen. `v0.24.3`.
- **T-Accounts screen** — shipped as `/t-accounts`, kept deliberately
  plain per your own "keep it simple": always the current month, one
  classic two-column ledger card per postable account with activity,
  grouped by type the same way Trial Balance's sections are, a bold
  total row on whichever side (Dr/Cr) the account's net for the month
  actually landed on. No date picker, no export — a teaching aid for
  double-entry itself, not another working report. `v0.25.0`.
- **Staging checkboxes behind SELECT** — same `body.select-mode`/
  `.select-only` mechanism the Journal's own "Select entries" already
  used; Approve/Reject stay visible throughout, just disabled until
  something's checked. Caught and fixed a CSS coupling in the same
  pass: the summary row's checkbox gutter used to be reserved
  unconditionally for Staging (its checkbox was always visible) — now
  conditional on `body.select-mode`, same as the Journal's own rule,
  so the row doesn't keep a blank gutter when nothing's shown in it.
  `v0.25.1`.
- **Staging entry origin text** — free with existing columns, as
  expected: `pending_staging_entries()` already LEFT JOINed
  `scheduled_entries`/`import_batches` for the target-scenario lookup,
  so this only needed two more columns off joins that already existed.
  Bottom right of each entry's expanded panel, dim and italic, next to
  Edit — "Created from schedule 'Rent'" or "Imported from file
  'march.csv' on 2026-08-26". `v0.25.2`.
- **MEMO click-to-edit** — click a line's memo in the Journal, it
  becomes a text input in place; Enter/blur saves via fetch, Escape
  cancels with no request at all. This one *did* need a schema change,
  as flagged: `fn_lines_immutable` used to reject every UPDATE on
  `journal_lines` unconditionally, so a real trigger carve-out (SPEC.md
  decision 16's own addendum) was required — scoped tightly to "memo
  changed, `entry_id`/`line_no`/`account_id`/`amount` didn't," enforced
  in Postgres itself, not just by which routes the app happens to
  expose. Works on any line, posted or still pending in Staging alike.
  Two new invariant tests cover it directly (memo-only update succeeds;
  a memo change bundled with an amount change still gets rejected).
  `v0.26.0`.
- **Manage duplicate entries on Staging — shipped Option 2** — a global
  FIND DUPLICATES link (no selection needed first) at `/staging/duplicates`,
  matching on the *full* leg set (same accounts, same amounts, same
  date, as a set, not a partial/pairwise check) so a 2-leg and a 3-leg
  entry can never accidentally match each other. Section headers reuse
  the Dashboard's own flow-arrow label ("Credit Card → Groceries").
  Checkboxes per entry, a single top Merge button, and — exactly as
  specified — a Proceed/Select remaining/Cancel dialog when some
  entries in a group were left unchecked, then a merge-detail popup for
  Description/Reference/Payee/Tags and one memo per line (candidates
  borrowed only from the matching account+amount leg on another checked
  duplicate, never guessed across a different one). Merging deletes the
  losing entries outright — legal because they're still pending Staging
  rows (decision 15), nothing to reverse. One real design write-up,
  SPEC.md decision 22, covering the matching rule, why one group merges
  per click (same shape as Payee/Tag Merge), and one deliberate
  simplification: no fake progress bar on the FIND DUPLICATES link
  itself, since the scan resolves before one would have anything real
  to report. `v0.27.0`.
- **Collapsible sidebar sections** — Ledger/Reports/Setup each toggle
  independently via a real `<button>` label with a chevron, collapsed
  state persisted per browser (one localStorage key per group). Chevron
  ended up on the right of the title after some back-and-forth during
  review — briefly tried on the left, reverted. `v0.27.1`.
- **Budget grid quick fill** — per-cell chevron with the four named
  options (last month's/3-month-average's ACTUAL or this scenario's own
  value), computed server-side once per page load
  (`_budget_rows()`'s own `quickfill` dict) rather than a round trip per
  click. Page-level "Set all values" applies the same two sources to
  every leaf cell at once, behind a real confirm since it overwrites the
  whole grid. Incidental fix along the way: the main Actual column's own
  negative-zero display bug for a zero-balance income account (`-0.00`)
  — same `signed()` normalize-at-the-source pattern
  `_income_statement_groups()` already uses. Advanced Options dialog and
  the row-select "Version 2" are explicitly deferred — see the item
  further down. `v0.28.0`.
- **T-Accounts → Ledger, follow-up fixes** — renamed the page (route,
  nav, title) to match paper bookkeeping's own terminology: a Journal
  records transactions in order, a Ledger is each account's own page.
  Each debit and credit now carries its own date (`Date  |  Debit  |  Credit
   |  Date`, dates on the outside per your own example row), and a strong
  rule between the Debit/Credit columns (`.t-divider`, same weight as
  the card's own caption border) actually draws the T — the ordinary
  `.money-first` hint border every other report's money column gets was
  never meant to read as a structural divider. Old `/t-accounts` URL is
  gone (404), no redirect kept — nothing outside this session ever
  linked to it.
- **Find Duplicates, follow-up fixes** — each group header gets its own
  "select all in this section" checkbox (same tri-state convention every
  other select-all here uses); the merge-detail popup's Payee field is a
  real combobox now, not a plain `<select>`, matching every other payee
  picker in the app. `v0.28.1`.
- **Bug: Memo click-to-edit doesn't save on iPad** — root cause traced to
  there being exactly one save path (blur/Enter), so anything that kept
  that one event from ever landing cleanly on a given setup (you saw it
  specifically with a hardware keyboard, not the on-screen one) lost the
  whole typed memo. Fixed by having the input autosave itself on a 600ms
  debounce while typing, so the server already has the latest text
  moments after the last keystroke — blur/Enter still does the normal
  "exit editing" save, it's just no longer the *only* thing that can
  persist it. Escape now does a corrective POST of the original value
  whenever a debounced draft already reached the server, so cancelling
  mid-edit still means cancel, not "revert on screen only." `v0.28.2`.
- **Bug: Budget grid quick fill "always writes 0" — not a bug.** Turned
  out to be exactly the data question flagged when this was investigated:
  testing in August with no journal activity before August, "last
  month"/"3 month average" correctly compute to 0 because there's
  genuinely nothing there yet. Confirmed by you on retest. No code
  change.
- **Bug: combobox "create new" shows "None" + typed text** — root cause:
  focus's own `input.select()` (meant to highlight the current value so
  the first keystroke replaces it, same as every other combobox on the
  page) is a documented no-op on some WebKit builds when called in the
  same tick as `focus()` itself — the platform's text-selection wiring
  isn't actually ready yet. The next keystroke then inserted into the
  still-unselected "None" instead of replacing it, e.g. "Noneabc". Fixed
  by deferring the `select()` one tick (`setTimeout(..., 0)`), the
  standard cross-browser fix for this exact class of bug — free on
  browsers that never had the problem, since it still finishes well
  before a human can physically type. Payee's the affected field (tags
  have no default "None"-style value to collide with). `v0.28.3`.
- **"No duplicate entries found" banner is green now, not red** — it was
  riding the generic `err=` flash path even though finding nothing is
  good news, not a failure. Switched to `ok=` (already exists, already
  green) rather than inventing a third flash color for one message.
  `v0.28.4`.
- **Confirmed + fixed: top-level account types weren't actually fixed.**
  Checked both `create_account` and `quick_create_account` — neither
  ever restricted `account_type` for a top-level (`parent_id` blank)
  account; a user really could create a second top-level Asset today.
  Deliberately *not* a hard DB constraint (a second top-level bucket of
  one of Asset/Liability/Equity/Income is a legitimate power-user
  pattern — e.g. splitting "Personal Assets" from "Business Assets" —
  and Expense is *meant* to have several top-level roots, see
  `db/seed.sql`'s own 5000-9000, so it's excluded from the check
  entirely). Shipped as a `confirm.js` warning instead, wired into both
  places a top-level account can be created — the "New account" panel
  and the tree view's own "+" quick-add — firing only when you already
  have one of that type. Also resolves the open "should Income be
  limited to one top-level account" reflection the same way, for all
  four types uniformly rather than singling out Income. `v0.28.5`.
- **Import single-entry files with rules → double entry** — shipped as
  `/import/mapped`, a second importer alongside the existing one for
  files that were never double-entry to begin with (ActualBudget's own
  CSV export is the concrete shape: Account, Date, Payee, Notes,
  Category, Amount). Upload, then map each distinct Account value found
  in the file to the real PostWarden account it represents (the money
  side) and each distinct Category value to the account it represents
  (the other side) — every mapping is a plain combobox, populated once
  from the file's own contents, nothing to name or save as a reusable
  ruleset (SPEC.md decision 23 — literally no new table, as you'd
  guessed). Submitting transforms every row into a real balanced
  double-entry posting and stages it in Staging exactly like the
  existing importer. Verified end to end against a synthetic
  ActualBudget-shaped file: an expense row, an income row, and your own
  Rule 2 example (a cash withdrawal) all produced correct balanced
  entries — the withdrawal specifically because "(no category)" was
  mapped to Physical Cash for that test file.
  **Known v1 limitation, written up rather than silently shipped**: this
  is two flat value→account mappings, not the conditional engine your
  own Rule 2 actually described ("IF account is X AND Notes contains
  'withdrawal'"). Every row sharing one blank Category lands against
  whichever single account got chosen for "(no category)" — fine when
  a file's uncategorized rows are all one kind of transaction, wrong
  when they're a mix (confirmed directly: an income row and a
  withdrawal sharing a blank Category in the same test file — one of
  them came out mapped to the wrong account, needing a manual reclass
  in the Journal after). A real condition-based version is a natural,
  separate follow-up if this gap matters in practice. `v0.29.0`.
- **Journal ↔ Staging homologation** — description is click-to-edit on
  both pages now (same `description-edit.js` shape `memo-edit.js`
  already established), replacing the Journal's old always-visible
  per-entry `<form>` entirely; Staging's own line memos are click-to-
  edit too, reusing `memo-edit.js` completely unchanged (its route
  already worked on a pending line — decision 16's addendum was never
  scoped to Staging status). Caught a real bug along the way:
  `pending_staging_entries()`'s own lines query never selected
  `journal_lines.id` at all (nothing had needed it before), so
  Staging's new `.memo-cell` would've silently carried an empty
  `data-line-id` — fixed in the same commit, before it ever shipped.
  `v0.29.1`.
- **Sticky report headers and leading columns** — the six report tables
  (Trial Balance, Balance Sheet, Income Statement including Split,
  Cash Flow, Variance, Budget Grid) keep their header row and their
  Code/Account columns in view while scrolling, CSS-only, no JS. The
  header sticks as one `<thead>` (carries Income Statement Split's own
  two-row header along together with no per-row math); Code/Account are
  two individually-pinned cells side by side, Code given a hard-pinned
  4.5rem width so Account's own fixed `left` lines up against it exactly
  (auto table layout treats a plain `width` as only a hint, which opened
  a real gap in testing before min/max got pinned to match). Caught and
  fixed a real bug from actually scrolling the Split view during testing,
  not just inspecting the CSS: naively targeting `thead th:first-child`
  without also scoping to its first row caught Split's *second* header
  row's own first two cells too (Code/Account's `rowspan="2"` means they
  never appear in that row at all), sticky-pinning the wrong cells and
  showing a stray "ACTUAL" bleeding under "CODE"/"ACCOUNT". `v0.29.2`.
- **Sticky headers, round 2 — the two bugs you found right after.**
  Both real, both fixed:
    - Top-level section titles ("Flexible & Lifestyle Expenses") weren't
      sticking horizontally — deliberately excluded in the first pass
      (that row's `colspan` cell would have been crushed by Code's own
      hard-pinned 4.5rem width), but that left the one row you actually
      need pinned most ("which section am I even looking at") with no
      sticky treatment. Fixed with its own rule — sticky `left: 0`, no
      width override, since a colspan cell's width already comes
      correctly from the columns it spans.
    - The header row genuinely didn't stick — but only on Income
      Statement Split specifically (`.table-scroll`, the one report
      wide enough to need its own horizontal-scroll box). Root cause:
      `overflow-x: auto` on that box silently forces `overflow-y` into
      being a real scroll container too (a CSS spec quirk — you can't
      keep one axis "visible" once the other scrolls), which hijacked
      the header's own sticky positioning before it ever reached the
      page. Fixed by leaning into it instead of fighting it:
      `.table-scroll` is now a genuine bounded pane (`overflow-x: auto;
      overflow-y: auto; max-height: 75vh`) with its own working sticky
      header inside — the same boxed-grid shape Google Sheets/GitHub's
      diff tables use for exactly this "too wide and too tall for the
      page" case. Every other report (no `.table-scroll`) is unaffected
      — confirmed Trial Balance still sticks straight to the page.
      `v0.29.3`.
- **UI consistency, round 1** — see `UI_CONSISTENCY_AUDIT.md` (the
  inventory + proposal you asked for) for the full write-up; this is
  its own §5 items 1-4, all four bundled into one commit:
    - One wording for "toggle whether this record is active," everywhere:
      **Archive/Unarchive** — replaces Accounts' Deactivate/Reactivate
      and Scheduled Entries' Pause/Resume (its own status column too:
      "paused" → "archived"), matching what Payees/Tags already said.
    - Ledger's zero-balance checkbox now says "show zero balances" like
      every other report, instead of a third distinct phrasing — the
      month-to-date scope moved to a `title=` tooltip instead of
      changing the word itself.
    - Balance Sheet's own two checkboxes were in the opposite order
      from Trial Balance's identical pair — swapped to match (zeros,
      then raw).
    - Find Duplicates gets the same Select-mode toggle every other
      checkbox-driven list in the app already has — its checkboxes used
      to be permanently visible, the one page that hadn't caught up to
      that pattern. Merge itself stays visible throughout regardless,
      same as Approve/Reject/Reverse/Merge everywhere else.
    - Budget Grid's explicit "Go" button is gone — auto-refresh already
      covered scenario/month changes, it was the only report that kept
      one.
    - Also decided, not built: Budget Grid **won't** get Export CSV/
      XLSX. It's a *working* view of the Variance report — editable
      inputs, not a finished number — Variance itself already has the
      export, and exporting a still-being-edited grid would just be
      exporting a draft.
  `v0.29.4`.
- **Sidebar: the group heading → Books, not the Ledger report** — first
  guess was backwards: the actual collision was the sidebar *group*
  heading (Journal/Staging/Scheduled Entries/Import/Templates/Budget
  Grid) also being labeled "Ledger," not the General Ledger report
  itself a few rows down under Reports, which is a real, correctly-
  named accounting term and needed to keep it. Fixed the group instead:
  its own button now says **Books** — "keeping the books" is exactly
  the working/recording side of accounting this group actually holds,
  and it reads naturally alongside its own siblings (Reports, Setup).
  `data-sidebar-key` stays the literal string `"ledger"` internally (an
  arbitrary localStorage identifier, no visible-text coupling) so
  nobody's saved collapse state resets over the rename.
- **UI consistency, round 2 (§5 item 5)** — Cash Flow gets the same
  Period preset dropdown (This month/Last quarter/...) Income Statement
  already had, since both pages ask the identical "what happened in
  this range" question. `period-picker.js` needed zero JS changes —
  already fully generic against `#period-preset`/`#date_from`/
  `#date_to` ids, and already a no-op on anything Income Statement
  Split-specific (`#totals-period-label`) that Cash Flow doesn't have.
  `v0.29.6`.
- **UI consistency, round 3 (§5 item 6) — prev/next navigation,
  everywhere a report has one anchor date or range.** Budget Grid had
  this already; nothing else did. One pattern *per archetype*, not one
  generic function, since "the next period" means something different
  depending on the question: Trial Balance/Balance Sheet/Variance (a
  single "as of" date) shift it by a calendar month, day-clamped so Jan
  31 minus a month lands on Dec 31 rather than an invalid date; Income
  Statement/Cash Flow (a `date_from`/`date_to` range) slide the whole
  window by its own length instead, so a custom range you typed by hand
  pages by its own span rather than snapping to a calendar boundary it
  never had. `docs/ARCHITECTURE.md` has the full writeup ("Prev/next
  navigation, one pattern per archetype").
  This closes out all seven `UI_CONSISTENCY_AUDIT.md` §5 items — see
  that file's own updated top note for the standing rule going forward:
  a report/list-page UI change now gets planned against its whole
  archetype (§1), not just the one page that prompted it. Also added to
  `CLAUDE.md`'s own working conventions, so it's not just on the record
  here. `v0.29.7`.
- **Staging: Clear filters moved inline** — Journal and Staging share
  the same combo boxes, but Clear filters sat one line below them on
  Staging while Journal kept it inline — matched to Journal's own
  position. `v0.29.8`.
- **Staging: Edit tags** — new button between Select and Approve, same
  behavior as the Journal's own Edit tags; the popup itself
  (`tags-bulk-edit.js`) got factored out of `entries-select.js` so both
  pages share one implementation instead of a second copy. Journal's
  own Select/Edit tags/Reverse buttons also reordered so Reverse comes
  last. `v0.29.9`.
- **Ledger reclassified as a point-in-time report** — gained the same
  **As of** date, **show zero balances**, and **show true balances
  (skip simulated close)** controls Trial Balance already had, reversing
  its original "always month-to-date, no picker" design (see
  `_ledger_rows()`'s own comment in `main.py` for the full writeup and
  what "raw"/simulated close means applied to individual lines rather
  than an aggregate balance). Bundled in the same pass: individual
  debit/credit amounts are clickable through to the source entry now,
  Credit picked up the red border it was missing against its own
  trailing Date column (previously only Debit had one), and the
  Debit/Credit divider was bumped from `1.5px` to `2px` after
  `getComputedStyle` showed the fractional width silently snapping to
  `1px` on a standard-density display. `v0.30.0`.
- **Budget Grid bug fixes** — Month is a real `<select>` now instead of
  `<input type="month">` (typing `2026-13` used to reach
  `date.fromisoformat()` as a raw `ValueError` and 500), with its own
  prev/next-month buttons back; "Set all values"' chevron is vertically
  aligned with its text, its dropdown menu no longer sits behind the
  sidebar, and it now offers the same four quick-fill options a single
  cell's own chevron does (SET ALL VALUES, all caps) instead of two.
  `v0.30.1`.
- **Prev/next links show the actual shifted period, not generic text**
  — Income Statement/Cash Flow said "Previous period"/"Next period";
  now they show the real shifted range (e.g. "← 2026-07"). Trial
  Balance, Balance Sheet, Variance, and Ledger got the same treatment.
  Variance's own scenario picker was also relabeled "Scenario" instead
  of "Baseline," matching Income Statement's wording for the identical
  control. `v0.30.2`.
- **Journal: hide-reversed checkbox repositioned** — moved below the
  Select/Edit tags/Reverse row, with that row now sitting inline with
  Export CSV/XLSX. Required generalizing `auto-refresh.js` from a
  per-form listener to one document-level delegated listener (via the
  standard `element.form` property), since the checkbox no longer lives
  inside the form it submits with. `v0.30.3`.
- **Variance: clickable amounts** — Baseline/Compare figures link
  through to the Journal now, same as every other report's own leaf
  amounts (decision 11, SPEC.md). Caught a real bug before it shipped:
  in rolled-up mode a row's account code is very often a summary
  account with nothing ever posted directly to it — fixed by checking
  each rolled-up target's real `is_postable` flag rather than assuming
  every row is linkable. `v0.30.4`.
- **Entry-id hyperlinks: the reversal badges** — "reversal of #X"/
  "reversed by #X" are real links now, backed by a new `entry_id`
  exact-match filter on the Journal (same shape as account/payee). The
  original ask ("every time an entry's id is displayed") turned out to
  have exactly one other instance in the whole app once actually
  grepped for. `v0.30.5`.
- **Import with rules: wording softened** — both intro paragraphs read
  as ActualBudget-exclusive when the real requirement is just matching
  column names; reworded to lead with "whatever budgeting app or bank
  export produces that shape," naming ActualBudget as the one this was
  tested against rather than the only thing accepted. `v0.30.6`.
- **Bug: combobox "— choose —" + typed text, round 2** — reported again
  on the Import-with-rules mapping page specifically. The round-1 fix
  (v0.28.3, defer `select()` one tick) still held on a real click/Tab
  focus when re-tested directly; the likely remaining gap is iOS
  Safari, where `select()` needs an explicit user gesture and can
  silently no-op regardless of timing — not something fixable by
  tuning a delay further. Sidestepped instead: a still-unset field
  clears outright on focus rather than trying to select the
  placeholder, so replacing it on the next keystroke no longer depends
  on selection actually taking effect anywhere. `v0.30.7`.
- **Option key (⌥) instead of "Alt+" on Mac/iPad/iPhone** — one
  `option-key.js` text-node sweep on load, rather than editing the ~15
  hardcoded "Alt+X" spots across entries/staging/scheduled/templates/
  help individually; a future shortcut hint anywhere just works. Every
  real shortcut listener still checks `e.altKey` unchanged — this only
  swaps the label. `v0.30.8`.
- **Confirmed, no code needed**: "Schedules can be activated and
  deactivated" — already true (Archive/Unarchive, from the UI
  consistency work). "Make ACTUAL and STAGING un-alterable like
  user-created scenarios" — also already true, though not for the
  reason expected: there's no rename/delete route for *any* scenario,
  so ACTUAL/STAGING were never specially exposed to begin with.
- **New import with rules page — all three items shipped.** Post-
  `v0.31.0`, no version bump of their own yet:
    - *Enter should move between combo boxes, not submit the form* —
      `Combobox.tsx` now moves focus to the line below on Enter, the
      same way a spreadsheet does (`a22688d`).
    - *Direct access, instead of reaching it via a link on another page*
      — the plain and mapped importers are two tabs on one Import page
      now, so neither is hidden behind the other (`4e83869`).
    - *A column mapping step instead of assuming column names* — the
      mapped importer is a three-step wizard (upload → map columns →
      review). `IMPORT_MAPPED_FIELDS` replaced the old exact-header
      requirement, which only ever worked because ActualBudget's own
      export happened to use those literal names; any single-entry CSV
      works now, whatever its columns are called. Backend `d30a3d5`,
      frontend `2991b2f`; `SPEC.md` decision 23 has the reasoning.
      **Shipped with the mapping table oriented target-field → file
      column, rather than the file-column → target shape specified in
      the original ask** — see `IMPORT_WIZARD.md` §2 for why, and why
      it's being flipped back.

## Feature: Every theme has a light and dark mode. 
- To move between themes and their light/dark variants, there is 
    - A theme combo box and 
    - A dark/light/follow system setting switch (the default is to follow system setting) 
- Log in page, defaults to “follow system setting” for dark/light theme when there is no stored record of the user’s preference
- Implementation implications: for every current theme you will need to create a corresponding light/dark variant

## Feature: Automatically add digits to all accounts automatically when there is an increase in account levels
- This would make account codes NOT chosen by the user.
- Each level added = one digit added. If only top level accounts exist (during first app open, etc.): Account codes are 1 digit (or maybe 2?)
- The user decides to add a level: Account codes automatically have a digit added to them. Example:
    - User adds level
    - “40 - Income” becomes “400 - Income” automatically
    - “41 - Interest Income” becomes “410 - Interest & Dividends Income” automatically
    - The user now has enough digits to add “411 - Savings Interest Income” and “412 - Stocks Dividend Income”
- I want you to tell me whether you think this has the risk of impacting other functionality. 
    - Under the previous example, if the user were to decide to add historical journal entries to reclassify or move balances from “410 - Interest & Dividends Income” to “411 - Savings Interest Income” in order to take advantage of their new accounts, would that affect cash flow statements? Or not, since the cash flow logic filters out income - income movements?
    - Use planning mode to think it through and let me know if you find such a case where this new feature impacts other functionality
- This also has te potential to affect the db schema. It wouldn't be visible to the user, but maybe account code IDs would now be a different field in the db than the account code the user sees.

## Feature: Remove accounts _(unsure of this)_
- While financial data should be immutable, maybe accounts could be deletable. When a user tries to delete an account PostWarden asks where the existing entry legs using that account should be redirected to.
- I see two ways this could be done:
    1. Existing journal entry legs are edited in the database
    2. A journal entry is posted to move all balances

## Desktop app
- The app leverages existing html, css, js, python and Postgres logic
- App setup wizard creates the necessary containers/services
- When the app is open the user can connect to Power BI

## First open/Initial setup 
- User can choose whether journal entries can be deleted or not. They are unable to change if afterwards _(unsure of this)._
- "Set up chart of accounts" experience. Maybe a special screen where adding a chart of accounts is more dynamic, like a fixed grid of accounts where the user can insert rows and click SUBMIT when they are ready.

## Ensure that the import functionality currently flags entries it can’t handle (unknown format, etc)
- It should preferably flag which lines it couldn’t read, e.g. “couldn’t read lines ”
- Absorbed into the import wizard plan as **R3** — see `IMPORT_WIZARD.md`.

## Documentation for user guidance:
- How do teach people who don’t understand double entry accounting and accrual basis
- How to setup chart of accounts
    - Is 4 digits enough? Maybe 5 or 6 to have enough depth? Considering different income and expense categories will pop up over the users life
    - The first digit: you only get 9 BIG buckets
        - Is it smart to have more than one income big bucket? Ie 4000 and 5000
        - How to decide the expense buckets, the heart of expense budgeting? You only get from 5000 to 9000 assuming you get (1 assets 2 liabilities 3 equity 4 income)
        - 9000 is used for passthrough in ERPs, would something like that apply here?
    - Recomendations for how to setup chart of accounts
    - What should the user do if they realize along the way they have been doing stuff wrong? If I were a user I’d want to export data, wipe everything, import into a new instance on staging, fix and post everything back

## Mobile app
- A user clones the repo, hosts it 
- They download the paid mobile app, which upon first open, asks for server/host, username and password to connect and retrieve data from their existing PostWarden instance
- The app has a “don’t have a PostWarden instance? Learn how to set it up on your computer” hyperlink that takes the user to documentation
- The user can create new transactions from the app
- The user can view reports from the app
- The mobile app’s aesthetics match that of the web app 

## Feature: Bank connection, maybe via the same providers ActualBudget uses.
- Check out SimpleFIN and similar services.

## Feature: PikaPods app for quick setup

## Documentation: Add Change Log

## New Report Option: income statement with months as columns. Future months have budget or other non-actual scenario numbers in them. 
- Cells corresponding to different fill or something to make it visually apparent that they’re not actual data.

## Report: Accounts Receivable and Accounts Payable management
- Set payment dates, both for when the user is the borrower and for when the user is the lender
- Total balance readout allows users to group transactions where money was loaned to and transactions where the money was lent from the same payee (friends and family would be the probable use case) so they can settle the balance with one single money exchange
- The user can export a report with these grouped transaction so they can share with the payee

## Feature: Export/import metadata (Chart of Accounts, scenarios, payees, tags) from csv files
- Would allow users to setup their desired metadata structure offline
- The *import* half is **R10** of the import wizard plan
  (`IMPORT_WIZARD.md`) — its steps 1–3 are identical whether the target
  is journal entries or a chart of accounts, which is why that plan says
  to build them target-agnostic even while shipping entries only.


- Auto calculate journal entries for loans, like car loans or mortgages. Add principal, interest rate, time period, etc.

- On “Budget Editor” page, features like “set value to last _ month(s) average”, “set value to last month”, “set ALL values to last month”, etc

- User Account types; Admin has access to a page where they can create, modify and delete other users that have varying read/write permissions

- Reset password/Forgot password functionality. Would require email capability.

- MFA.
- Feature: “Asset Manager” (Objects, Tangible Assets, Fixed Assets, etc. ; Manager): A page where you create assets that appreciate/deteriorate. You set the rules (residual value, useful life, etc) and the app handles the journal entries for you.
- Payment reminder. Scheduled payments coming up widget on dashboard.
- “Send to email button” for reports. Other emails like reminders for upcoming payments.
- Manage imports: Manage file templates, choosing delimiter, separate debit/credit columns, thousands and decimal indicator, contains header row, etc. — absorbed into the import wizard plan (`IMPORT_WIZARD.md`): the delimiter/decimal/header settings are its **phase 2**, separate debit/credit columns its **phase 4**, and saved file templates its **R5**.

- Add “is cash flow account” attribute to accounts. That way we can make cash flow reporting. 

## Custom themes
- Is this easily doable? Is it worth it?

## Add support for different languages

## Add graphs to reports/create new reports
- Cash flow
    - Waterfall
    - Cash flow graph (line graph or bar chart, goes under 0 axis for net negative cash flow months)
        - Bar chart could be net or could show positive movements and negative movements
- Income statement
    - Pie/donut chart for income and expense distribution (total for all displayed periods)
    - Waterfall chart (total for all displayed periods)
    - Bar chart, months as columns, total expense as bar height, color categories for expense accounts
- Balance Sheet
    - Assets to Liabilities
    - Liquidity

## Budget grid quick fill — still open
- Shipped: per-cell chevron (4 options) and the page-level "Set all
  values" dropdown (2 options) — see Done above.
- Still not built, deliberately deferred:
    - "Advanced Options" dialog — "Set to last [N] month(s) [average,
      total, min or max] of [SCENARIO] Scenario." Explicitly a "maybe in
      the future" in the original ask.
    - Version 2: a SELECT button + per-row checkboxes on the Budget Grid,
      so the bulk dropdown can target just the selected rows instead of
      every cell on the grid.

## I want to understand the current scenario functionality
- Is the scenario type combo box is only a label?
- The actual functionality of the scenario is chosen with two other buttons ("enforce balance" and "income statement"). Is the "scenario type" label necessary?
- Alternatively, should the “is income statement only” and “enforce balance” constraints be chosen automatically depending on scenario type? This would make four distinct scenario types.
- However, reading the current documentation I see that two of the four possible scenario combinations apparently do the same thing (when "income statement only" is on the "enforce balance" option does not change anything, if I'm not mistaken). If that's the case, I don't want the user to be confused between two seemingly different options that actually do the same thing.

## Connection with Power BI and external reporting tools
- In previous conversations we realized that it's not that easy to just use the PostgreSQL connector on Power BI and connect to ¨mypostwardeninstance.somehostingservice.com¨, since the Power BI PostgreSQL connector doesn't have an HTTP connection, it has a TCP one. And we can't just expose the PostgreSQL db to anyone for security reasons. If the end user decides to do so, that's on their own accord.
- Therefore, if a user wants to connect to Power BI with the PostgreSQL connector on a remotely hosted instance, they have to tweak with their host's network configuration, which is out of PostWarden's control, meaning it can't make it friendly to not-that-tech-savvy users.
- This is partly what inspired the Desktop App idea above. If the user were to download a Desktop app and set it up without much tweaking then Power BI could connect to the local db instance without the need to tweak with settings.
- In the current scenario, we should at least clearly document the steps the user can take to be able to use a reporting tool, the ones I identify are:
    - Set up PostWarden in your local computer, not remotely
    - Open up the PostgreSQL instance to anyone using TCP (risky)
    - Tweak with their hosting settings and install some stuff on their computer and host. Let's document the options specifically so the users can get going
    - Export reports and journal data to a tabular format file
- In order not to extend the reach of PostWarden and be a "jack of all trades" that just does lots of stuff mediocrely, we decided that PostWarden should do one thing and do it well. Currently that means accurate bookkeeping. However, we have introduced basic reporting. "Doing one thing and doing it well" _could_ mean being a one-stop solution for all your personal finance needs, including a data model and reporting capabilities, but only if we can get it right.
- However, reporting is an important need for personal finance. Given that we should commit to one of two roads:
    - Seriously explore a method of making connecting to a PostWarden instance from a reporting tool be relatively easy
    - Develop robust enough reporting needs that a user would never want to use a reporting tool (extremely hard).

## Multicurrency
- Journal entries have a currency

## Import XLSX files
- Import files button allows CSV and XLSX files
- Absorbed into the import wizard plan as **R7** — see `IMPORT_WIZARD.md`.
  Cheap *if* its phase 2 abstraction boundary ("file → table of strings,
  nothing format-specific downstream") actually holds; expensive to
  retrofit if it doesn't, which is why that boundary gets built before
  there's a second format to justify it.

## Automatically flag possible duplicates
- This logic could run on the db
- When a new entry is added to staging, before the db runs 'INSERT INTO...', it runs a SELECT query looking for entries that exist with the same date, accounts and amounts
- The output is passed on, and the user gets a yellos warning banner on their dashboard saying "Possible Duplicates Found [Go to Staging ->]". The same banner appears no Staging itself, except the link text indicates that it will filter the suspected duplicate entries, something like "Possible duplicates found. [Show possible duplicates ->]"

## Make Midnight the default theme and Modern Sans Serif the default font

## Export ledger (t accounts) report

## New journal entry form improvements
-  Issue 1: 
    - Navigate to the account drop down menu by pressing tab repeatedly
    - The drop down menu displays and an element is highlighted
    - If you press tab again the highlighted element is not input into the field, it stays blank
    - Maybe (and I want your feedback for this) the top element on the account drop down menu should say _None_ in itallics, that way the use is forced to use their arrow keys to navigate to an account and there is no ambiguity of whether he was just passing by the account drop down or actually wanted an account
- New logic:
    - When the distribute button or its corresponding keyboard shortcut is pressed:
        - If there is no selected account for that row, then the account field for that leg should instantly become the highlighted field so the user can choose the account straight away
        - If there is a selected account for that row, then the amount field for that leg should instantly become highlighted, because there is no need to navigate quickly to choose an account, it's already been chosen

## Keyboard navigation improvements:
- Add a keyboard shortcut to edit tags button
- Add a keyboard shortcut for SELECT (entries) on journal and staging, and when checkboxes are displayed:
    - Navigate between entries with tab (current behavior)
    - Check the checkbox of the currently highlighted journal entry with one keystroke


## If for some reason a user prefers to actually post closing entries
- Meaning, they want to post entries to manually move income statement balances to equity at month close
- Make an option on user settings that says something like "ALWAYS DEFAULT TO SKIP SIMULATED CLOSE", "MANUAL CLOSE" or something like that, if they toggle it then that's the default
- Discourage from doing so in the docs, or add a section 'Do I need to post closing entries every period?'

## Reflection: Should the following things be chosen for the user or give them freedom?
- Having current and non-current assets/liabilities as the immediate accounts below assets and liabilities
- Limiting them to only ONE top level income account (4000) — resolved
  below (warn, don't lock) the same way for all four of Asset/Liability/
  Equity/Income, not just Income specifically.

## Reflection: Reversals, should they be posted to the same date that the entry they were reversing was posted?

## Accounts page
- Change "MARK AS CASH" button wording to something different

## The import wizard — planned in `IMPORT_WIZARD.md`, not here

The three original "New import with rules page" items have all shipped
(see Done above). The plan that replaced them is a much larger one, on
the stated assumption that **the wizard eventually becomes the only
import path in PostWarden**, for double-entry and single-entry files
alike, retiring both of today's importers.

That plan lives in [`IMPORT_WIZARD.md`](IMPORT_WIZARD.md) rather than as
a backlog bullet, because it's a real design document — a seven-step
spine, twelve requirements, a schema-impact table, and five phased
implementation steps. Short version:

- The mapping table gets **flipped** to the file-column → target
  orientation originally specified (one row per column in the file,
  defaulting to *Ignore*), which is the only shape that forces an
  explicit decision about every column rather than silently dropping the
  ones nobody picked.
- A **dialect step** (delimiter, decimal/thousands separator, date
  format, header row) is what actually unblocks "any bank's CSV" — a
  European export using `;` and `1.234,56` fails today with no control
  anywhere to fix it.
- One wizard subsumes both importers once it can answer **"does one file
  row equal one entry, or do several combine into one?"** — that single
  question is the whole difference between them.
- **No wipe-and-rebuild.** Every schema change it implies (saved
  profiles, a duplicate-detection hash, large-file staging) is a purely
  additive Alembic migration.

Several existing backlog items below are absorbed into that plan and
should be read against it rather than picked up independently: "Ensure
that the import functionality currently flags entries it can't handle"
(its R3), "Manage imports: Manage file templates, choosing delimiter…"
(its R5 and phase 2), "Import XLSX files" (its R7), and "Export/import
metadata … from csv files" (its R10).

## How come Income Statement only scenarios don't get to pick base level?
- That was the original intended use case, that if a user wants to do an expense budget they might want to just assing a total number to a rollup of the Actual Scenario

## Should more reports have the SKIP SIMULATED CLOSE button?

## Should UI be React.js? — done
Yes. Rebuilt on the `rebuild` branch and merged to `master` as `v0.31.0`
(2026-08-30): FastAPI + Jinja2 + vanilla JS replaced by a vertical-slice
FastAPI backend (SQLAlchemy Core, Alembic) serving a JSON API to a React
+ TypeScript SPA. See `docs/ARCHITECTURE.md` for the resulting shape and
`SPEC.md`/`git log` for the reasoning kept from the planning that led
here.