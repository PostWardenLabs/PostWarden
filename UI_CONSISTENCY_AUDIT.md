# UI Consistency Audit — AS-IS inventory and TO-BE proposal

Written in response to a direct request: go through each page, inventory
its controls, then propose a streamlined shape so a report doesn't make
the user re-learn a different set of filters/buttons every time they
land on a new page. All seven proposed changes in §5 have since shipped
— see each item's own strikethrough note for what actually landed.

**This file is the standing reference for planning any future report
UI change, not just a historical record of this one pass.** §1's four
archetypes (Filterable transaction list, Point-in-time report,
Range/period report, Editable grid, plus Management/CRUD) are the
actual unit of design from here on — a change to how one report's
filter bar looks or behaves gets planned against *every other report in
its archetype* before it's built, the same way §5.6's prev/next
navigation was designed once per archetype (point-in-time vs. range)
and applied identically across every report in each, rather than
invented per page. Also see `docs/ARCHITECTURE.md`'s own "Sticky header
row..." and "Prev/next navigation..." sections, which document the two
concrete patterns that came out of thinking this way.

Method: read every page template in `app/templates/`, grepped for every
`<form>`, `<select>`, `<input>`, `<button>` on each, cross-referenced
against `style.css`'s own component classes and `auto-refresh.js`/
`combobox.js` for the shared JS behavior underneath. Not run through the
browser page by page — this is a structural read of what's actually
rendered, not a visual QA pass (the "Bug fixes" work item covers a few
things this audit's own reading also surfaced).

---

## 1. The pages fall into four real archetypes, not one

They don't all need the same controls — a Journal filter and a Balance
Sheet's "as of" picker are answering different questions. The
inconsistency worth fixing isn't "why doesn't every page have every
field," it's that **pages already doing the same job don't agree with
each other**. Four archetypes, as currently built:

| Archetype | Pages | What it's answering |
|---|---|---|
| **Filterable transaction list** | Journal (`/entries`), Staging (`/staging`) | "show me the entries matching X" |
| **Point-in-time report** | Balance Sheet, Trial Balance, Variance | "what do balances look like as of a date" |
| **Range/period report** | Income Statement, Cash Flow, Ledger | "what happened between two dates" (Ledger's range is fixed to MTD, not user-picked, but it's still range-shaped) |
| **Editable grid** | Budget Grid | "let me change numbers, not just read them" |
| **Management / CRUD list** | Accounts, Payees, Tags, Scenarios, Account Levels, Scheduled Entries, Templates | "let me create/edit/retire records" — a genuinely different job from the five above, its own section at the end |

The TO-BE proposal (§4) defines one canonical control set **per
archetype**, not one for the whole app — that's the actual fix for
"every report has a different set of filters, combo boxes, checkboxes."

---

## 2. AS-IS inventory

### 2a. Filterable transaction lists

| Control | Journal (`entries.html`) | Staging (`staging.html`) |
|---|---|---|
| Scenario | `<select name="scenario">`, real "All" option | `<select name="target_scenario">`, real "All" option |
| Date range | From / To (`type="date"`) | From / To (`type="date"`) |
| Free-text search | Search field + submit icon (`qtext`) | Same |
| Tags | Tag-chip filter input | Same |
| Account | `<select name="account">` | Same |
| Payee | `<select name="payee">` | Same |
| Amount | Operator `<select>` + one or two amount inputs | Same |
| Extra toggle | "hide reversed/reversals" checkbox | *(none — a pending entry can't be a reversal)* |
| Clear filters | `<a class="button-link">Clear filters</a>` | Same |
| Select mode | "Select" button → reveals checkboxes + "select all" | Same |
| Bulk actions | Reverse (Alt+R), Edit tags | Approve (Alt+A), Reject (Alt+R) |
| Export | CSV, XLSX | *(none — nothing here is posted yet)* |
| Row-level edit | description/memo click-to-edit | description/memo click-to-edit (added this session) |

**Verdict: already the most consistent pair in the app** — literally the
same shared filter-building code (`_shared_journal_filters`) and mostly
the same template shape. The differences that remain (hide-reversed,
bulk-action verbs, export) are real, deliberate differences in what the
two pages *are*, not accidental drift. Nothing here needs unifying.

One real sibling, though: **Find Duplicates (`staging_duplicates.html`)**
is reachable only from Staging and has no "Select" toggle at all — its
checkboxes are permanently visible, unlike every other checkbox-driven
list in the app (Journal, Staging, Payees, Tags all hide theirs behind
Select). Worth a look — see §3.

### 2b. Point-in-time reports

| Control | Balance Sheet | Trial Balance | Variance |
|---|---|---|---|
| Scenario picker(s) | 1 (`scenario`) | 1 (`scenario`) | **2** (`baseline`, `compare`) — a different shape, not just a naming difference |
| Roll up to (account level) | — | — | `<select name="level_id">`, unique to this page |
| As of | `<input type="date" name="as_of">` | Same | Same |
| Checkbox 1 | "show true balances (skip simulated close)" | "show zero balances" | "show zero balances" |
| Checkbox 2 | "show zero balances" | "show true balances (skip simulated close)" | "Flip variance direction" |
| **Checkbox order** | raw, then zeros | zeros, then raw | zeros, then flip |
| Export | CSV, XLSX | CSV, XLSX | CSV, XLSX |
| Explicit Go button | none (auto-refresh) | none | none |

The **raw/zeros checkbox order is flipped between Balance Sheet and
Trial Balance** for no reason either page's own comments explain — pure
copy-paste drift. Small, but it's exactly the kind of thing that makes
two nearly-identical pages feel like they weren't built by the same
hand.

### 2c. Range/period reports

| Control | Income Statement | Cash Flow | Ledger |
|---|---|---|---|
| Scenario | `scenario` | `scenario` | `scenario` |
| Compare to | `compare` (2nd scenario) | — | — |
| Split | Monthly/Quarterly/Yearly `<select>` | — | — |
| **Period preset** | `<select id="period-preset">` (This month/Last month/This quarter/...) — client-side only, fills From/To | — (no preset at all) | — (no date picker at all, fixed to MTD) |
| From / To | `type="date"` × 2 | `type="date"` × 2 | *(none)* |
| show zero balances | yes | — | yes, but worded **"show accounts with no activity this month"** instead |
| Flip variance direction | yes, only if `compare` set | — | — |
| Export | CSV, XLSX | CSV, XLSX | **none** |

Income Statement's **period-preset dropdown is genuinely useful** (This
month / Last quarter / etc., computed client-side) and **exists on no
other date-range page** — Cash Flow's own From/To has no such shortcut,
despite asking the exact same kind of question ("what happened in this
range"). That's a real, valuable feature stuck on one page instead of
generalized.

Ledger's zero-balance checkbox wording ("show accounts with no activity
this month") is arguably *better* than the generic "show zero balances"
elsewhere — it says what it actually means on a report with no date
picker at all — but it's now a third distinct phrasing for what
Balance Sheet/Trial Balance/Income Statement/Variance all call "show
zero balances."

### 2d. Editable grid (Budget)

| Control | Budget Grid |
|---|---|
| Scenario | `scenario` |
| Month | `<input type="month">` — **the only page using `month` instead of a date/date-range** |
| **Explicit "Go" button** | present, despite `data-auto-refresh` already firing on scenario/month change — the only report-shaped page with a visible submit button |
| Prev/next navigation | `&larr;`/`&rarr;` links either side of the current month — **the only report with this**, despite Income Statement/Cash Flow/Trial Balance/Balance Sheet all being just as period-shaped |
| Flip variance direction | yes |
| Set all values | page-level bulk-fill button, unique to this page |
| Export | **none** |

The month-typing bug (BACKLOG.md: typing `2026-13` 500s) lives here —
see the Bug fixes section below, not this doc.

### 2e. Management / CRUD pages

These are a different job (create/edit/retire a record) and mostly
*shouldn't* look like a report's filter bar — but the specific words
used for "this record is currently inactive" genuinely do vary for no
reason tied to any real difference in meaning:

| Page | "Currently active" toggle says |
|---|---|
| Accounts | **Deactivate** / **Reactivate** |
| Payees | **Archive** / **Unarchive** |
| Tags | **Archive** / **Unarchive** |
| Scheduled Entries | **Pause** / **Resume** |
| Scenarios (a different concept — `is_locked`, not `is_active`) | Lock / Unlock — fine, this one *is* a different thing |

Three different verbs (Deactivate, Archive, Pause) for the identical
underlying `is_active` toggle across four record types. Scenarios'
Lock/Unlock is correctly left alone — locking isn't the same concept as
retiring a record, so it earning its own word is right, not drift.

Select/Merge shape: Payees and Tags already share one identical
pattern (`Select` toggle → checkboxes → `Merge`, disabled until 2+
checked) — this one's already consistent and is the right model to
extend, not replace.

`accounts.html`'s own "Mark as cash" / "Unmark cash" button — flagged
directly in `BACKLOG.md` as unclear wording, own item below.

### 2f. Structural note (invisible to the user, still worth naming)

Every filter form on the report/list pages is functionally identical
(`data-auto-refresh` or `class="bar"`, wired up by the same
`auto-refresh.js`), but two different markup shapes produce that
behavior — `<form class="bar">` directly (Staging only) vs.
`<form data-auto-refresh><div class="bar">...</div></form>` (everyone
else, because a second row of checkboxes/export links needs the form
itself to not be the flex container). Not a user-visible bug, but worth
knowing before touching any of these — Staging is the one filter form
shaped differently underneath despite looking identical on screen.

---

## 3. Concrete inconsistencies found, ranked by how much they'd actually confuse someone

1. **Three different verbs for "toggle whether this record is active"**
   (Deactivate/Reactivate, Archive/Unarchive, Pause/Resume) — §2e. A
   user who's learned Payees' "Archive" has to re-learn "Deactivate"
   means the same thing on Accounts.
2. **The zero-balance checkbox has three different names**
   ("show zero balances," "show accounts with no activity this month,"
   and — on Balance Sheet — always paired with a *different-meaning*
   "show true balances" checkbox right next to it in a different order
   each time) — §2b, §2c.
3. **Budget Grid is the only report with an explicit Go button** even
   though every field on it already auto-submits — a leftover control
   that no other report kept, and that does nothing the auto-refresh
   doesn't already do.
4. **Income Statement's period-preset dropdown (This month/Last
   quarter/...) exists on exactly one page** despite Cash Flow asking
   the identical "what happened in this range" question with plain
   From/To only.
5. **Prev/next period navigation exists only on Budget Grid** despite
   every other date-anchored report (Balance Sheet/Trial Balance's "as
   of," Income Statement/Cash Flow's range) being just as natural a fit
   for it.
6. **Export CSV/XLSX exists on five of seven report pages** — missing
   on Budget Grid and Ledger. Ledger's absence is a *documented,
   deliberate* choice ("a teaching aid, not a working report" — Done
   log, `v0.25.0`). Budget Grid's absence has no such note anywhere —
   worth deciding on purpose rather than leaving as an accident.
7. **Find Duplicates has no Select-mode toggle** — its checkboxes are
   always visible, unlike every other checkbox-driven list in the app.
8. **Balance Sheet and Trial Balance's own two checkboxes are in
   opposite order** — copy-paste drift, no functional difference.
9. `accounts.html`'s "Mark as cash" wording, flagged directly in
   `BACKLOG.md`.

---

## 4. TO-BE proposal

### 4a. One wording, one verb, per concept — app-wide

| Concept | Adopt |
|---|---|
| Record active/inactive toggle | **Archive / Unarchive** everywhere (Payees/Tags' existing word) — replaces Accounts' Deactivate/Reactivate and Scheduled's Pause/Resume. "Archive" already reads correctly for all three: an inactive account, payee, tag, or schedule is exactly "put away, not deleted, can bring back." |
| "Include rows with a zero balance" | **"Show zero balances"** everywhere, including Ledger — Ledger's own extra context ("...this month") can stay as a `title=` tooltip or a one-line `.page-sub` note instead of changing the checkbox's own label, so the *word* stays identical while the page still explains its own scope. |
| Scenario picker | Always labeled **"Scenario"** (Journal already does this; Staging's "Scenario" meaning *target* scenario is explained in a comment today — make that explicit on-screen too, e.g. a field hint, not just a code comment) |

### 4b. Per-archetype canonical control set

**Point-in-time reports** (Balance Sheet, Trial Balance, Variance) — one
row: Scenario(s) → As of → [Roll up to, Variance only] → checkboxes in
one fixed order: **zero balances, then true/raw balances, then flip
variance** (only the ones that actually apply to a given page — Balance
Sheet has no flip, Variance has no raw). Add **prev/next day or prev/
next month** shortcuts next to "As of," the same shape Budget Grid
already proved out — cheap, and every one of these three pages is
answering a "move the anchor date" question just as often as Budget is.

**Range reports** (Income Statement, Cash Flow) — Scenario [→ Compare
to, Income Statement only] → **Period preset** (promote Income
Statement's own dropdown to both pages — this is the single highest-
value unification here, since Cash Flow asks the identical question
with strictly worse tools today) → From/To → checkboxes. Ledger stays
the deliberate exception (no date picker, by design) but keeps the same
checkbox wording as everyone else per §4a.

**Editable grid** (Budget Grid) — Scenario → Month → prev/next (already
has this) → **drop the explicit Go button** (auto-refresh already
covers scenario/month changes; keep it only if a future change needs a
real "these are staged, not yet applied" distinction, which quick-fill
today doesn't) → Flip variance → Set all values. Decide Export CSV/XLSX
on purpose either way, and if "no" — note why, the same way Ledger's own
"no export" is already on the record.

**Filterable transaction lists** (Journal, Staging) — already the
target shape; no change proposed beyond giving Find Duplicates the same
Select-mode toggle every other checkbox list already has (§3.7).

**Management/CRUD** (Accounts, Payees, Tags, Scenarios, Levels,
Scheduled, Templates) — keep the existing Select/Merge pattern
(Payees/Tags) as the model; apply the unified Archive/Unarchive wording
(§4a) everywhere an `is_active`-style toggle exists. Leave Scenarios'
Lock/Unlock alone (different concept, correctly named differently
already).

### 4c. What this deliberately does *not* propose

- Making every report have every filter — Cash Flow doesn't need a
  free-text Search the way Journal does; a rollup-to-level picker on
  Balance Sheet would be adding a control nobody asked for. Consistency
  here means "the same question gets the same control," not "every
  page grows to the union of every other page's controls."
- A visual redesign of the controls themselves — `combobox.js`,
  `datepicker.js`, `.checkline`, `.bar` are already applied uniformly
  site-wide; this audit is entirely about *which* controls a page shows
  and *what they're called*, not how a `<select>` renders.

---

## 5. Suggested sequencing, if you want to move on this

Roughly cheapest-and-safest first, each independently shippable:

1. ~~Wording unification (§4a) — text-only changes, zero behavior risk.
   Archive/Unarchive on Accounts/Scheduled; zero-balance wording on
   Ledger.~~ **Shipped** — Accounts/Scheduled now say Archive/Unarchive
   (Scheduled's own status column too: "paused" → "archived"); Ledger's
   checkbox now reads "show zero balances" with the month-to-date scope
   moved to a `title=` tooltip instead of the label itself.
2. ~~Balance Sheet/Trial Balance checkbox order fix — one-line swap.~~
   **Shipped** — Balance Sheet swapped to zeros-then-raw, matching Trial
   Balance's own (already-correct) order.
3. ~~Find Duplicates gets a Select-mode toggle.~~ **Shipped** — same
   `body.select-mode`/`.select-only` mechanism as everywhere else;
   Merge itself stays visible throughout, same as every other
   bulk-action button in the app.
4. ~~Drop Budget Grid's redundant Go button.~~ **Shipped** —
   `data-auto-refresh` already covered scenario/month changes.
5. ~~Promote Income Statement's period-preset dropdown to Cash Flow.~~
   **Shipped** — `period-picker.js` needed zero JS changes, already
   fully generic against `#period-preset`/`#date_from`/`#date_to`.
6. ~~Prev/next date navigation on Balance Sheet, Trial Balance,
   Variance, Income Statement, Cash Flow.~~ **Shipped** — one pattern
   *per archetype*, not one generic function: point-in-time reports
   (Trial Balance/Balance Sheet/Variance) shift their single "as of"
   date by a calendar month (`_shift_date_by_month`, day-clamped);
   range reports (Income Statement/Cash Flow) slide the whole
   `date_from`/`date_to` window by its own length (`_shift_range`), so
   a custom range pages by its own span rather than snapping to a
   calendar boundary it never had. See `docs/ARCHITECTURE.md`'s own
   "Prev/next navigation, one pattern per archetype" section for the
   full writeup.
7. ~~Decide + implement Budget Grid Export CSV/XLSX~~ **Decided,
   deliberately not built**: Budget Grid is a *working* view of the
   Variance report (editable inputs, not a finished number) — Variance
   itself already has the export. Exporting a still-being-edited grid
   would be exporting a draft, not a report.

All seven items done — 1–4 bundled into one commit as planned; 5–6 each
got their own commit and a doc update, per this repo's own convention;
7 was a decision recorded on the record, not code. See the note at the
very top of this file for how §1's archetypes now govern planning any
future report UI change.
