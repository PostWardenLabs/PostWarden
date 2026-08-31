# PostWarden roadmap — the master plan

**This is the only file in this repo that contains plans.** Created
2026-08-31 by consolidating five planning documents that had each grown
their own isolated phasing — `BACKLOG.md`, `CUSTOM_REPORTS.md`,
`FORECAST.md`, `IMPORT_WIZARD.md`, and `UI_CONSISTENCY_AUDIT.md` — into
one coherent sequence (§11 maps where each file's content went; git
history holds all five in full). The division of labor from here on:

- **`ROADMAP.md`** (this file) — what's next and why, in what order.
- **`SPEC.md`** — why shipped things are shaped the way they are.
  When a phase here ships, its design reasoning moves there as a
  numbered decision; it does not accumulate here.
- **`docs/SCHEMA.md` / `docs/ARCHITECTURE.md`** — what exists.
- **`README.md` / `docs/GUIDE.md`** — what a user gets and how to
  think about it.

Maintenance rules, learned from what went wrong with the five files
this replaced: **no Done log** — a shipped phase gets a one-line ✅
with a pointer to its SPEC decision and commits, and its detail is
deleted from here (commit messages are this project's changelog;
`BACKLOG.md`'s 500-line Done section was a second, drifting copy of
git log). **No phasing anywhere else** — a design exploration can grow
notes wherever it needs to, but the moment it has an ordering opinion,
that opinion lives here or it doesn't exist. Internal planning:
deliberately **not** in `mkdocs.yml`'s nav, not published to
docs.postwarden.org.

---

## 1. Vision

PostWarden is becoming a **whole-financial-life tool built on a ledger
the database itself guarantees** — three layers, each one only
trustworthy because of the layer beneath it:

1. **Record** — double-entry bookkeeping that PostgreSQL enforces at
   the schema level. This exists and is the foundation everything else
   is derived from. It is deliberately boring from here on: the
   invariants are done, the 60 pure-Postgres tests hold them, and no
   phase below weakens any of them.
2. **Understand** — reporting. Today: seven bespoke report pages plus
   a composable Report Builder. Target: **one reporting surface** the
   user composes — tabs and widgets over the same closed, pre-vetted
   query vocabulary — instead of a sidebar of developer-authored pages.
3. **Plan** — the differentiator, and the reason to use PostWarden
   *instead of* a cashflow tool rather than alongside one: projecting
   the ledger forward (schedules, commitments, budgets) and answering
   **"can I afford this?"** from the books themselves. YNAB derives
   its famous goal math from envelope allocations; PostWarden derives
   strictly more from real double-entry state — a liability's balance
   *is* the live "remaining," and projected cash *is* the runway.

The product thesis for all three: personal finance apps succeed when
they **click with the user's natural mode of thinking**. The natural
model has three spaces — *putting data in*, *looking at what it
means*, *deciding what to do next* — and the app's structure should be
exactly those spaces, not a sidebar that enumerates implementation
units. Features that compete with each other, or two screens that
answer the same question differently, are bugs against this thesis
even when each is individually fine.

## 2. Principles every phase answers to

Standing constraints, distilled from `SPEC.md` and this consolidation.
A phase that can't be built without breaking one of these is a phase
that needs redesigning, not an exception:

1. **The database enforces the accounting; the app can only misreport,
   never corrupt.** Nothing below touches the append-only triggers,
   the balance constraint, or hierarchy integrity.
2. **A dimension, not a module — for ledger-shaped data, and the bar
   stays high** (SPEC decision 3; reviewed 2026-08-31). When new data
   is an attribute of the *same money* — it partitions or overlays the
   very postings the ledger already holds — it's a dimension on the one
   fact table (scenario was the first; **project**, §6.3, is the
   second), because the alternative is parallel bookkeeping that needs
   reconciling. When it's a *different kind of fact* — a budget figure,
   a due date, a goal — it gets its own table, and only queries join it
   to the ledger (`budget_lines`, commitments, targets are all this
   shape, deliberately). The test: would a module mean duplicating or
   reconciling postings? Dimension. Is it new information about intent
   or the future? Own table. And a new dimension is never cheap or
   reversible — it touches the fact table and every consumer of it, and
   adds a grouping mechanism users must be taught — so each one needs
   the case the project dimension made (§6.3), not a reflex.
3. **Derived numbers are queries, never postings** (SPEC decision 10,
   extended forward in time). The simulated close, a projection, a
   target's "required per month" — all recomputed on read, none stored.
   This is what makes them self-correcting for free.
4. **Closed allowlists at every trust boundary** (SPEC decision 25).
   A report config, a widget config, an import mapping — enums and
   typed parameters end to end, never a query language or a free-form
   field name from the client.
5. **One component per archetype** (`docs/ARCHITECTURE.md`,
   "Component archetypes"). A UI change is planned against every
   screen in its archetype, not the one page that prompted it. The
   S-track below exists to *reduce* the archetype count, and any new
   screen that adds one back needs to justify itself.
6. **Schema stability is a v1 promise, not a today promise.** Until
   v1 — the point where real ledgers run on real instances — schema
   changes are fair game, including breaking the baseline, whenever
   that's what the right shape costs; don't contort a design to stay
   additive. From v1 on, nothing forces a wipe: Alembic migrations
   apply automatically at startup (see README "Updating"), and every
   change ships as a migration plus the `db/schema.sql` baseline
   update. (Reframed 2026-08-31 — the old "would this feature force a
   rebuild?" anxiety is retired in both directions.)
7. **Docs ship with the feature; one revertable commit per unit of
   work** (`CLAUDE.md`). Multi-day phases get feature branches — a
   push to `master` auto-deploys beta.

Two former principles were reviewed out on 2026-08-31: *"the URL is
the config"* is demoted to a working convention (kept where it's free
— see §3.2 — but no phase answers to it), and *"no double-entry
vocabulary required"* is dropped — PostWarden is a double-entry ledger
and doesn't apologize for it; screens phrase things well, but debits
and credits are not a cost to be hidden.

## 3. The target shape

### 3.1 Three sections, not eleven sidebar links

| Section | Holds | Today's equivalent |
|---|---|---|
| **Reports** | One tabbed, widget-based surface (§3.2) — the landing page | Dashboard + the seven report pages + Report Builder, as separate sidebar links |
| **Data Entry** | Journal, Staging, Scheduled Entries, Import, Templates, Budget Grid | The "Books" group, unchanged in content |
| **Settings / Admin** | Accounts, Levels, Scenarios, Payees, Tags, Projects (once P1 ships), Help, account settings, BI connection | The "Setup" group + Settings |

**There are no links to specific reports anywhere in the sidebar.**
The Reports section is one entry; which reports a user sees, and in
what order, is their own curation (§3.2). A user who never opens Trial
Balance never sees Trial Balance.

### 3.2 The Reports surface

One screen, tabbed. Rules that make it one system rather than a frame
around the old pages:

- **The tab owns the controls; widgets inherit them.** Scenario and
  the date/period anchor live on the tab's control bar; every widget
  on the tab renders against them. A widget may pin an override
  ("always MTD"), shown on the widget itself. This is the load-bearing
  rule — it's what stops a Balance Sheet tab from quietly re-becoming
  a bespoke page.
- **A tab keeps a real URL** (`/app/reports/<tab>?scenario=…&as_of=…`),
  and existing report URLs redirect to their tab equivalents. A working
  convention rather than a product principle (reviewed 2026-08-31) —
  kept because it's nearly free and the saved-reports mechanics (S5)
  already ride on validated-config-in-the-querystring.
- **A widget is a report config rendered small.** One registry, one
  contract (`{key, title, size, config, href}`), two families behind
  it: *statement-derived* widgets (summaries of the classic
  balance-sheet/income-statement/cash-flow services — no new backend)
  and *composable* widgets (a saved Report Builder config — S5). Every
  widget's header links to its full report.
- **Default layout** (what a fresh instance shows):
  - **Overview tab**, row 1: Net Worth card (balance sheet), a P&L
    card (Total income / Total expenses / Net income), a Cash Flow
    card (Cash in / Cash out / Net cash). Row 2: net worth over time
    (line), expenses over time by category (stacked bar), cash flow
    waterfall. Below: Recent activity, Upcoming transactions, and the
    Staging-pending banner — today's dashboard content, carried over.
  - **Balance Sheet, Income Statement, Cash Flow tabs** — each one
    full-width report widget plus its archetype's control bar.
  - Trial Balance, Ledger, Variance, Report Builder: available from
    an always-present "All reports" affordance, not shown by default.
- **Curation** (S3): pin/unpin/reorder tabs; add, remove, move, and
  resize Overview widgets; "Add to Overview" from any Report Builder
  config. Stored server-side (§10 decision D5) so a user's app is the
  same on every device.

### 3.3 Archetypes: six → four

The three report archetypes (Point-in-time, Range/period, Composable)
merge into **one**: the Reports surface. What remains:

| Archetype | Screens |
|---|---|
| Reports surface | every tab and widget above |
| Filterable transaction list | Journal, Staging |
| Editable grid | Budget Grid (and P3's planning mode, P5's plane grid) |
| Management / CRUD | Accounts, Payees, Tags, Scenarios, Levels, Scheduled, Templates, Projects |

The per-archetype control conventions (one wording per concept,
canonical control order, prev/next semantics) live in
`docs/ARCHITECTURE.md`'s "Archetype conventions" section — that part
of the old UI audit is a standing reference, not a plan, and moved
there.

### 3.4 What the data model grows

Everything below is additive. In order of appearance:

- `user_preferences` (S3) — tab/widget curation, JSONB per user.
- `saved_reports` (S5) — named, validated Report Builder configs.
- `projects` + `journal_lines.project_id` (P1) — the project
  dimension.
- `scheduled_entries.end_date` / `remaining_occurrences` (P2) —
  schedules stop projecting to infinity.
- `fn_projected_cash` (P2) — the projection, a set-returning function
  like `fn_trial_balance`.
- `commitments` + `commitment_due_dates`, `targets` (P4).
- `budget_lines` gains the project dimension in its PK (P5 — delicate
  after v1; fair game before it, per principle 6).
- Import-track additions when their phases arrive: `import_profiles`
  (R5), a duplicate-detection hash column (R4), a TTL'd upload table
  (R8).

## 4. The sequence at a glance

Three tracks. **S runs first, in order** (the "clean order" decision,
D6 in §10): the reporting surface finishes before the planning track
starts, so P's three new screens land on the new structure instead of
paying the reorganization cost twice. **I and Q interleave freely** —
they touch the import pipeline and small standalone items, independent
of both.

| Phase | Delivers | Schema | Depends on |
|---|---|---|---|
| S1 | Matrix table component (headless), TB + BS ported | — | — |
| S2 | Three-section nav + tabbed Reports surface | — | — |
| S3 | `user_preferences` + tab/widget curation | ✚ | S2 |
| S4 | Overview tab: widget host + default cards | — | S2 (S3 for curation) |
| S5 | `saved_reports`, `balance` metric, second dimension, add-as-widget | ✚ | S3, S4 |
| S6 | Income Statement, Ledger, Variance ported to S1's component | — | S1, S2 |
| S7 | Waterfall chart type, `budget_variance` metric | — | S5 |
| P1 | The project dimension | ✚ | — (see note) |
| P2 | Schedule end conditions + `fn_projected_cash` | ✚ | — |
| P3 | Projected Cash Flow tab + planning mode | — | S-track, P2 |
| P4 | Commitments, targets, cockpit, affordability dialog | ✚ | P1, P2 |
| P5 | Budget planes | ✚ (PK) | P1, P4 |
| P6 | Guided first-run path | — | P2/P3 |
| I1–I5 | Import: profiles, conditional rules, XLSX, duplicate hash, large files | ✚ each | pain-driven, any time |
| Q | Small standalone items (§8) | — | any time |

P1 is sequenced after the S-track by default, but it has no dependency
on it — if a real project needs attributing before the S-track
finishes (life doesn't wait for refactors), P1 can run early; it's an
additive migration and its UI cost before any project exists is zero
(§6.3).

## 5. Track S — the reporting surface

### S1 — the matrix table component

Adopt **TanStack Table (headless)** as the renderer for every
hierarchical/columnar report table (D4, §10). Headless is the point:
it provides row/column models only, so the existing
`table.ledger.report-table` markup and the entire stylesheet survive
by construction — the constraint is *don't lose the current
capabilities and aesthetics* of the report tables, and a styled grid
library (AG Grid, MUI) would mean re-approximating them instead.
It replaces, with first-class equivalents, the three things currently
hand-rolled: column groups (Income Statement Split's two-row
`rowSpan`/`colSpan` header math), expanding sub-rows
(`useCollapsibleTree`'s ancestor-walk hiding), and pinned lead columns
(the sticky Code/Account cells inside `.table-scroll`).

Not a drop-in: TanStack's expansion model is nested (`getSubRows`)
while the report APIs return flat rows with `parent_id`/`depth`, so
the component builds the tree client-side; and `useCollapsibleTree`'s
localStorage persistence is re-expressed as controlled `expanded`
state (keep the per-report storage keys so nobody's collapse state
resets). Port **Trial Balance and Balance Sheet only** in this phase —
the two simplest tree reports, as the proof that aesthetics really
survive. No user-visible change is the acceptance criterion.

Why first: once users can compose report shapes a developer never
hand-built (S5), every shape needs a generic renderer. Migrating the
renderer *after* users' saved configs point at it means rewriting the
widget layer under load.

### S2 — the three-section shell and the tabbed surface

- `shell/nav.ts` collapses to the §3.1 structure. The Reports group
  becomes one entry; Books becomes Data Entry (rename only —
  `data-sidebar-key` stays `"ledger"`, an arbitrary localStorage
  identifier, so collapse state survives); Setup absorbs Settings
  under one Settings/Admin heading.
- The Reports surface mounts at `/app/reports` with tabs per §3.2;
  the Overview tab initially *is* today's `DashboardPage` content;
  the report tabs initially wrap the existing page components
  unchanged — this phase is navigation and frame, not rendering.
- Every old report URL (`/app/balance-sheet`, …) redirects to its
  tab. Old bookmarks keep working forever; the redirect is three
  lines a route.
- The "All reports" affordance lists every report with a one-line
  description — the discoverability guarantee that lets the sidebar
  drop per-report links without stranding Trial Balance and Ledger.

### S3 — preferences and curation

One `user_preferences` table (user_id, JSONB), one Alembic migration.
Holds the §3.2 curation state: visible tabs and their order, Overview
widget layout, per-tab pinned overrides. Server-side deliberately —
this state defines what the user's app *is* and must follow them
across devices, which is a different kind of thing from the
view-toggle presentation state SPEC decision 12 keeps in the browser.
That distinction (composition vs. presentation) gets written up as a
SPEC decision addendum when this ships; existing localStorage
conveniences (tree collapse, sidebar pin) stay browser-side under
decision 12 unchanged.

### S4 — the Overview tab as a widget host

The widget registry and contract (§3.2), plus the statement-derived
default widgets: the Net Worth card, the P&L three-row card, the Cash
Flow three-row card — all summaries of services that already exist
(`modules/reports/`), so no new backend beyond three small summary
endpoints (or one, batched). Recent activity / Upcoming transactions /
the Staging banner become widgets in the same registry (they already
render from `GET /dashboard`). The three chart widgets in the default
row 2 arrive in S5/S7 when the vocabulary can express them — until
then row 2 is simply absent from the default layout.

### S5 — saved reports, and the metrics that make widgets real

The v2 the Report Builder was designed for, plus the enum additions
the default chart widgets need:

- **`saved_reports`** — the config columns (metric, dimension, filters
  JSONB, chart_type) as TEXT with CHECK constraints, Python enums
  staying the source of truth; validation happens on every run, not
  just at save (the config is replayed through the same
  enum-validated GET). CRUD via the Management archetype; "Save" on
  the Report Builder; "Add to Overview" on any saved report.
- **`balance` metric** — point-in-time balance via `fn_rollup_balance`
  per period bucket, the first *stock* metric alongside the existing
  flow metrics. This is what makes "net worth over time" a config
  instead of a bespoke page.
- **Second dimension** (split-by/stack-by) — still enum × enum, one
  extra `GROUP BY` shape per pair, doubling no trust surface. This is
  what makes "expenses over time by category" (month × account-level,
  `account_type=expense`) a config.
- **Value-level include/exclude checklist** — check/uncheck specific
  accounts/tags from the dimension's own value list; a validated
  `IN (...)` clause, not a new input kind.

With these, Overview's default row 2 ships two of its three charts as
built-in saved-report configs.

### S6 — port the remaining reports

Income Statement (the hard one — Split's period × compare × variance
column groups), Ledger, and Variance move onto S1's component; the
bespoke table implementations are deleted. Cash Flow's
sectioned-statement shape and Budget Grid's editable cells are
explicitly *not* forced onto it — Budget Grid stays the Editable grid
archetype, and Cash Flow migrates only if the component genuinely
expresses it (decide when porting, don't pre-commit). Sweep the
`skip simulated close` question (§8) as part of planning this port —
whichever reports should have it, add it while their control bars are
being rebuilt once, per archetype.

### S7 — the last chart pieces

The **waterfall chart type** (Recharts has no primitive — it's a
stacked bar with a transparent base series; real work, budgeted as
such) and the **`budget_variance` metric** (joins `v_monthly_activity`
to `budget_lines`; only valid with a month-family dimension and a
budget scenario chosen — the one metric with a validity rule, which
is why it waits for the enum machinery to be boringly solid). Ships
the third default chart: the cash-flow waterfall widget. Also unlocks
the old "income statement with months as columns, future months from
budget" wish as a config rather than a page.

## 6. Track P — projection, commitments, targets, and the project dimension

*(Absorbed from `FORECAST.md`, 2026-08-31, with §9.1 decided: the
project dimension is adopted (D2, §10). The rejected alternative — a
polymorphic tag-or-subtree target scope with CoA-governance rules —
lives in git history under `FORECAST.md` §4B and dies unbuilt.)*

### 6.1 The core insight

YNAB's celebrated goal behavior is one division recomputed live:
`required_per_month = remaining ÷ months_left`, self-correcting when
you pay. Booked the double-entry-native way (Dr Expense / Cr A/P at
signing; Dr A/P / Cr Cash on each payment), **the liability account's
balance *is* the live "remaining"** — no parallel goal bookkeeping,
nothing to reconcile. The ledger already stores strictly more than
YNAB keeps. What the schema can't yet hold is *when things come due*;
what the app can't yet do is *project forward*. So the whole track is
two additions and a principle:

1. **Due-date structure** on balances (commitments) and goals
   (targets).
2. **A projection engine** expanding schedules, commitments, and
   budget lines into a future cash picture.
3. **The projection is a query, never a posting** (principle 3, §2) —
   nothing materializes, everything recomputes, which is exactly what
   makes it self-correct.

The emotional target: the PostWarden equivalent of feeling "YNAB
poor" is *projected closing cash dips below your buffer in some
future month* — same psychological effect, derived from the ledger,
and more honest because it sees liabilities cashflow-only tools can't.

### 6.2 What already exists

Verified against `db/schema.sql`: scenarios already model what-if
overlays (SPEC decision 3 — no new primitive needed for §6.7's
planning mode); `budget_lines` is the budgeted stream;
`scheduled_entries` is the scheduled stream but **has no end
condition** (projects to infinity — P2 fixes); `accounts.is_cashflow`
defines "cash" (same set as the Cash Flow Statement); reversal
machinery covers commitment cancellation. Tags are entry-grain and
many-to-many — which is precisely why they can't be the project
mechanism (§6.3).

### 6.3 The project dimension (P1) — adopted

The "dimension, not module" move applied a second time: a chart of
accounts encodes a transaction's **nature**; "wedding" is a
**purpose**. Purposes get a dimension, not a subtree.

**Schema:** `projects(id, code, name, color, is_active, notes)` — a
curated attribution key, no amounts or dates (money-planning lives on
targets). **`journal_lines.project_id`, nullable FK** — line grain,
like every ERP; `NULL` = general life, which is most lines forever.
Also on `scheduled_entry_lines` and template lines so recurring
entries stamp their occurrences. `v_fact_lines` gains the column; the
star schema gains `dim_project`.

**The property tags can't give: sums that partition.** A line belongs
to exactly zero-or-one project, so project totals sum back to the
ledger total and mixed entries split honestly at the line — that
partition is what makes a dimension a *reporting axis* rather than a
label. Tags stay what they are (overlapping descriptive labels);
`docs/GUIDE.md` must teach the roles crisply — nature → accounts,
exclusive attribution → project, overlapping labels → tags — because
a third grouping mechanism users pick wrongly is worse than none.

**UX at line grain, kept effortless:** before any project exists the
app looks exactly like today (empty `projects` ⇒ no picker, no chip,
no card — zero new load). After: one **Project** picker on the entry
form defaulting every line, per-line override for the honest
mixed-entry split ($120 groceries General / $60 favors WEDDING on one
Costco run); payee memory pre-selects; schedules/templates carry it.
Journal/Staging and the report filters gain one chip-rendered filter
— including **"General only"** (`project_id IS NULL`), the sleeper
feature: *your life without the wedding*, no mental subtraction.
`/projects` is a standard Management/CRUD roster; the import wizard
gains a mappable project target; the CSV export/re-import round-trip
carries it.

**Blast radius, priced honestly:** the fact table (the most protected
object in the schema — the nullable column is additive, append-only
triggers and the 60 invariant tests shouldn't notice), scheduled/
template lines, the entry form, import, export round-trip, seed/demo
data, every filter bar. Each piece small; the sum is a real,
independently shippable phase, useful with nothing else in this track
built. One open decision rides with it (O1, §10): whether
`project_id` on a *posted* line is editable in place (attribution
metadata, like the entry header's description — decision 4's
precedent) or immutable-fix-by-reversal; it would be the first
line-level field with the in-place treatment and needs its own SPEC
decision either way.

### 6.4 Commitments (P4) — due-date structure on a balance

`commitments(id, account_id, description, target_id NULL, status, …)`
plus `commitment_due_dates(commitment_id, due_date, amount NULL,
refundable_until NULL)` — a payment plan; one row with a single final
date is the minimal case. Everything else **derived, never stored**:
remaining = the account's balance; required pace = remaining ÷ months
left; behind/on-track = required vs. original pace.

**Symmetric from v1** — not hardcoded to liabilities. "My parents
pledged $5,000, half in January" is A/R with due dates, and the
projection's *inflow* rows update exactly like a vendor's outflows.
This one shape absorbs the old A/R–A/P management backlog item.
Lifecycle: `draft` (a saved quote — feeds affordability, not the
tracker) → `active` → `closed` / `cancelled` (reversal machinery, same
gesture). `refundable_until` lets the tracker report "of $13,100
paid+committed, $6,000 still recoverable." Lifecycle extras beyond
active/closed can trail as fast-follows.

### 6.5 Targets (P4) — an envelope with a deadline

`targets(id, name, amount, deadline, project_id, buffer NULL,
status)` — scope is simply the project (the payoff of D2; no
polymorphism). A target exists *before* any contract does, so it
cannot require a booked liability. Derived, never stored — the three
colors of money YNAB can't see: **Paid** (actual postings in scope),
**Committed** (linked commitment accounts' balances — booked, cash
not yet gone), **Unclaimed** (amount − paid − committed).

Two independent health checks, because there are two ways to be off
track: **pace** ((amount − paid) ÷ months left vs. original monthly
pace — the YNAB recalc, derived) and **solvency** (re-run the
projection assuming the full target still gets spent — does closing
cash at the deadline clear the buffer? Catches perfect wedding pace
while *life* overspent underneath). The target amount stays fixed
(auto-shrinking would hide the problem); the UI shows the solvency
*margin trend*. A `closed` target freezes its story; closing offers
to retire its project in the same gesture.

### 6.6 The projection function (P2)

`fn_projected_cash(from, to)` — set-returning, callable from app,
psql, or BI alike, combining without materializing: opening cash
(actual `is_cashflow` balances), the **scheduled** stream (virtual
forward-expansion of recurrence rules — requires the new
`end_date`/`remaining_occurrences` columns), the **committed** stream
(`commitment_due_dates`; remaining ÷ remaining-dates when amounts are
null), the **budgeted** stream (a caller-chosen budget scenario,
summed across all project planes — plane separation is an editing
concept, not a cash concept, §6.8).

**Daily grain internally, monthly presentation** — monthly close can
look fine while Feb 3 (rent out, salary not in, deposit due) goes
negative, and vendors love deposit due dates. Surface a per-month
**lowest point** (`low: $1,240 on Feb 3`); buffer checks run against
the low, not the close. Build the grain in from v1 — retrofitting
grain into a projection function is painful.

**The precedence rule** (the one hard problem — decided deliberately,
O2 in §10 to confirm before building): per (account, month, project),
**scheduled entries beat budget lines** — a schedule is a dated
fact-to-be, a budget number a working assumption for accounts with no
better information. Superseded budget lines show struck/grayed, never
silently dropped. Commitments only touch cash + their own
balance-sheet account, so they collide with budgets only when the
user budgets the *payment* instead of the expense — a modeling error
the report surfaces, not resolves. Deferred but designed-for:
credit-card settlement timing (a March card swipe leaves cash in
April).

### 6.7 The user-facing surfaces

All landing on the S-track's structure — the projection report is a
tab, the trackers are widgets, and the cockpit is assembled from
existing archetypes. The one genuinely new screen is the cockpit.

- **Projected Cash Flow tab (P3)** — months as columns, rows grouped
  by stream (opening / scheduled / committed / budgeted / closing /
  low) so supersession is visible. Headline: projected cash at range
  end minus buffer ⇒ "up to $X is unclaimed." Committed/budgeted rows
  optionally break down by project chip. v1 grain (cash totals vs.
  account rows) is O3.
- **Planning mode (P3)** — the tweak-until-satisfied loop: clone the
  operating budget into a working scenario (cloning is what makes
  tweaking safe), budgeted rows become live editable cells
  Budget-Grid-style, the headline recomputes per keystroke; "Commit
  this plan" promotes the clone and creates the target in one
  gesture. Nothing ever posts to the journal.
- **Target tracker (P4)** — a widget: paid/committed/unclaimed bar,
  both health checks, amber when either trips, with the corrected
  monthly number.
- **Affordability dialog (P4)** — "can I afford this?": amount,
  payment schedule, which target. Three checks in order — category
  (fits the project plane's sub-allocation? offer reallocation),
  envelope (fits unclaimed?), cash timing (overlay the payments as a
  `draft` commitment on the projection — does any month's *low*
  breach the buffer? suggest a date that clears it). Verdict with
  reason and suggestion; "yes" books the entry, the commitment, and
  the target link in one click.
- **The project cockpit (P4)** — opening a project lands where its
  whole story lives: tracker header + affordability button, then
  three panels — the allocation grid (this project's budget plane,
  a filtered Budget Grid: natural accounts down the side, Budgeted /
  Committed+Paid / Left per row, an Unallocated remainder), the
  commitments list (due dates, refundable-until, A/R pledges as
  inflows), and the Journal pre-filtered to the project. Feel target:
  *everything about the wedding on one screen, nothing about the
  wedding required anywhere else.* **Close project** on the cockpit
  retires target + project + offers tag cleanup in one confirmation;
  the cockpit stays reachable (filter: Closed) as a frozen
  retrospective. In year ten the entry form's picker holds only what
  you're doing in year ten.
- **The app speaks first** — upcoming-payments widget (due dates make
  it real), and state-change alerts ("Feb low dropped below buffer")
  computed lazily on request (no task runner — SPEC decision 9's
  constraint stands; push/email stays parked with the other email
  features).
- **Optimism stays quarantined** — money you shouldn't plan on (cash
  gifts) lives in an optimistic overlay scenario: visible as upside,
  excluded from every yes/no verdict.

### 6.8 Budget planes (P5)

With budget-by-project, a budget scenario's lines live in **planes**:
one per project plus the **General plane** (`project_id IS NULL` —
exactly today's grid, so the day-one experience is unchanged). The
grid shows and edits **one plane at a time** (a switcher next to the
scenario picker); there is deliberately **no summed editable view** —
if March Dining shows 550 (250 General + 300 wedding) and the user
types 500, no rule can say which plane absorbs the −50; a summed
editable cell is ambiguous by construction. Reading is different:
sums happen at read time (an optional read-only combined view; the
projection always consumes the sum). Variance is per-plane against
project-filtered actuals. This is the `budget_lines` PK change —
deferrable (P4's cockpit ships its allocation grid read-only against
targets until P5 lands), but it's what makes the envelope's
sub-allocation *per-category planning against natural accounts*.

### 6.9 The design line that must hold

- **Per-project pace, global solvency.** Projects partition
  attribution; they share **one cash reality**. There is no
  per-project projection report — wedding pace ✅, honeymoon pace ✅,
  both cards green, and the global check still flags February because
  the flight deposit and the band deposit land in the same tight
  month. That interaction is the single-repository argument applied
  to the future, and tools that silo projects cannot give it. The
  affordability dialog's envelope check asks "against which project?";
  its cash-timing check always runs against everything.

### 6.10 The first-run path (P6)

The projection is only trustworthy once opening balances,
`is_cashflow` flags, and schedules exist — none of which onboarding
asks for today, so a newcomer going straight to Projected Cash Flow
gets a confidently wrong picture. Guided first run: (1) opening
balances as one entry against an Opening Balances equity account —
"your car-loan spreadsheet becomes one line"; (2) flag the cash
accounts in the same breath; (3) schedules — paycheck, rent, loans
(principal/interest introduced as a benefit, not homework); (4) a
rough budget, framed as a working assumption; (5) payoff screen: the
runway — end on the projection showing *their* number. The marketing
insight buried here: **no history import needed** — the projection
runs on today's balances plus forward-looking data. "Start with four
balances tonight, be projecting by bedtime" belongs in `README.md`'s
pitch and `docs/GUIDE.md`'s getting-started when this ships.

### 6.11 Acceptance scenario (condensed)

Engaged Aug 31, wedding June 12 (~10 salary cycles); cash $12,400;
salary +$5,500/mo scheduled; rent+loan −$2,250/mo; ~$1,400/mo
budgeted variable. (1) *Sizing*: projection reads $26,240 closing;
minus $5,000 buffer ⇒ $21,240 unclaimed; planning mode trims to
$23,800; commit a $20,000 target → project WEDDING, sub-allocated on
its plane (Venue 9,000, Photo 2,500, Music 1,500…). (2) *Booking*:
venue signed ⇒ Dr venue expense / Cr A/P 9,000; commitment 3,000 now,
6,000 due May — the May outflow appears in the projection the instant
the contract books; parents' pledge ⇒ A/R inflows in January.
(3) *Tracking*: Paid 4,100 / Committed 9,000 / Unclaimed 6,900; both
checks green; "General only" answers whether the rest of life is on
plan. (4) *Band $3,500 vs. DJ $1,200*: band fails category (Music
1,500 — offer reallocation) and timing (Feb low $680 under buffer —
suggest Mar 15); DJ is green³; one click books the winner.
(5) *After*: close target+project; retrospective forever queryable;
pickers as clean as year one. The track ships when this walkthrough
works end to end.

### 6.12 Fast-follows (after P5, pain-ordered)

What-if overlay UI on the projection, commitment lifecycle extras +
`refundable_until` surfacing, state-change alerts, credit-card
settlement timing, the loan amortization generator (absorbs the old
"auto calculate journal entries for loans" item — a generator on top
of commitments), per-project chip breakdown rows on the projection,
Balance Sheet ratio widgets (assets vs. liabilities, liquidity — the
one old graph wish that isn't a metric × dimension config; as summary
cards they're widgets, not reports).

## 7. Track I — the import wizard, remaining work

The wizard itself shipped (SPEC decisions 23–24; `v0.31.1`) and is the
only import path. Its twelve requirements keep their numbers here
(code comments reference them). Shipped and now recorded in SPEC:
R1 sniff-first, R2 real-data preview, R3 per-row validation report,
R11 single funnel, R12 pure functions. Remaining, in value order:

- **R5 — saved import profiles** (I1). Steps 1–4 save as a named
  profile, auto-matched on upload by column-name fingerprint; value
  maps sticky ("SAFEWAY #1234 was Groceries last month, propose it").
  New `import_profiles` table (+ value-map rows) — the deliberate
  reversal of decision 23's "no saved ruleset," which was right for a
  second optional importer and wrong for the only one; decision 23
  gets its addendum when this ships. Nobody should redo the wizard
  monthly for the same bank.
- **R6 — row-level conditional rules** (I2). The documented v1
  limitation: every blank-Category row lands on one chosen account,
  so an income row and a cash withdrawal sharing a blank Category
  can't both be right. A small ordered rule list per row — `IF
  <column> <contains|equals|starts with|matches> <value> THEN <leg> =
  <account>` — first match wins, falling back to the value map. Pure
  transform if rules stay per-import; combine with R5 to persist per
  profile.
- **R7 — XLSX and friends** (I3). Cheap *iff* the "file → table of
  strings, nothing format-specific leaks past step 1" boundary held
  (it was built for this). OFX/QFX/CAMT only if real files show up.
- **R4 — duplicate protection** (I4). "12 of these 90 rows match
  entries already in your ledger" at preview time; a per-entry source
  hash (one nullable column) makes it exact, and feeds the shipped
  `/staging/duplicates` page plus the old auto-flag wish (a Staging
  banner on insert-time matches).
- **R8 — stop base64-ing large files** (I5). Above a threshold, park
  the upload server-side with a TTL, pass an id. Driven by real file
  sizes, not speculation.
- **R9 — splits**: a *single row* expressing a multi-way split is
  still undecided (grouped rows already work) — decide, don't omit
  (O7).
- **R10 — metadata import** (chart of accounts, payees, tags,
  scenarios from CSV): wizard steps 1–3 are already target-agnostic
  by design; steps 4–6 need a target abstraction. Pairs naturally
  with P6's first-run (set up your CoA offline, import it).
- Cosmetic, any time: rename `/import/mapped/*`, `Mapped*Request`,
  `ImportMappedPanel.tsx` → the unqualified names — "mapped" is a
  misnomer now that it's the only importer (confirmed deliberate
  least-churn deferral).

## 8. Track Q — small standalone items

Any-time, one-sitting items; straight to `master` per convention.

- **Entry form focus logic**: Distribute (button or shortcut) focuses
  the row's account combobox when unset, the amount field when set;
  fix Tab committing nothing when the dropdown highlight was only
  passed through (the *None*-first-option idea).
- **Keyboard nav**: a shortcut for Edit Tags; a shortcut for Select
  mode on Journal/Staging plus a keystroke to check the highlighted
  row.
- **Staging field hint**: "Scenario" on Staging means *target*
  scenario — say so on-screen.
- **Accounts page**: "Mark as cash" wording (flagged twice; pick the
  words when touching that page).
- **Ledger export**: decide yes/no on purpose (O8) — its absence was
  deliberate as a teaching aid, but it's been reclassified as a real
  point-in-time report since.
- **Default theme**: make Midnight + Modern Sans Serif the defaults.
- **Scenario UX questions** (O6): whether scenario_type should drive
  the two constraint toggles instead of sitting beside them as a
  label, and whether income-statement-only scenarios should pick a
  base level — answer both together, they're one "what is a scenario
  type" question.

## 9. Parked — deliberate, with revisit triggers

Not a graveyard; each has a named trigger. Anything not listed here
or above was either shipped or absorbed (§11).

| Item | Why parked | Revisit when |
|---|---|---|
| Theme light/dark variants (+ follow-system switch) | 22 themes × 2 variants is real work; orthogonal to every track | after S-track, as one polish pass |
| Custom themes, i18n | same polish family | with the above |
| Mobile app (thin client on the JSON API) | product surface still moving; the API is already the contract | after P-track stabilizes the surface |
| Desktop app (packaged containers + local BI) | same, plus it's mainly a Power BI delivery vehicle | with the above; revisit against the BI docs item |
| Bank connection (SimpleFIN et al.) | wants R5/R4 first so imports are low-friction and dedup'd | after I-track's R5+R4 |
| PikaPods / one-click hosting | marketing surface, cheap late, wasteful early | when courting non-technical users |
| Multi-user permissions, MFA, password reset email | multi-user tier; single-user self-host is the product today | if/when a hosted offering is real |
| Asset Manager (depreciation schedules) | same machinery family as the loan generator | after the loan generator ships (§6.12) |
| Multicurrency | shape already decided: currency on entries + a `prices` table, never per-account (SPEC extension roadmap) | when a real multicurrency user exists |
| Email anything (reports, reminders) | no task runner by design (SPEC decision 9) | only with a deliberate SPEC reversal |
| Manual closing entries option | discourage; the simulated close is the product's answer (decision 10) | write the "do I need closing entries?" GUIDE section instead |
| Auto account-code digit growth | user codes are load-bearing UX; migration churn for cosmetic gain; risks confusing history | if CoA levels ever become user-invisible |
| Remove/delete accounts | append-only philosophy: only the "post a reclass entry, then archive" shape is admissible; archive already covers the picker-hygiene need | if archive proves insufficient in practice |
| Entity dimension, fiscal periods & closing | SPEC's extension roadmap; projects (P1) is the near-term sibling | unchanged |
| Remote BI connection docs | Connect page shipped; what remains is documenting tunnel/hosting options honestly | docs pass alongside P6 |

## 10. Decision register

Decided in this consolidation (2026-08-31):

- **D1 — One plan file.** This document; the five planning files
  deleted, content absorbed per §11.
- **D2 — The project dimension is adopted** (old FORECAST §9.1).
  Line-grain nullable `project_id`; target scope = project; the
  polymorphic fallback dies unbuilt. Rationale: the multi-year
  whole-financial-life vision is the point of the product, and
  building targets against the wrong scope means designing the same
  feature twice.
- **D3 — Reports is one tabbed widget surface; no per-report sidebar
  links; the tab owns the controls.** §3.1–3.2.
- **D4 — TanStack Table, headless**, as the matrix renderer; the
  existing markup/stylesheet survives. §5 S1.
- **D5 — Curation state is server-side** (`user_preferences`), because
  composition-of-the-app is not presentation-of-a-view; SPEC decision
  12 addendum due at S3.
- **D6 — Clean order**: S-track completes before P-track starts
  (P1 may move early if a real project needs attributing; §4).
- **D7 — The changelog is `git log` + `VERSION`**; no CHANGELOG file,
  no Done log here.

Open, with a due-by (decide before, not during):

- **O1** (due P1) — is `journal_lines.project_id` editable in place on
  posted lines (attribution metadata, decision-4 precedent) or
  fix-by-reversal? First line-level in-place field either way ⇒ its
  own SPEC decision.
- **O2** (due P2) — confirm schedule-beats-budget precedence per
  (account, month, project); is a per-account override needed, or is
  showing the superseded number enough?
- **O3** (due P3) — projection report v1 grain: cash totals + stream
  groups only, or account-level rows from the start?
- **O4** (due P4) — where the buffer lives: user-level setting,
  per-target, or both with per-target overriding?
- **O5** (due P4) — does booking from the affordability dialog record
  entry↔commitment provenance (like `scheduled_entry_id` does), or is
  the account linkage enough?
- **O6** (any time; ideally before P3's planning mode clones
  scenarios) — the scenario-type questions bundled in §8.
- **O7** (due I-track pickup) — R9 single-row splits: in or out.
- **O8** (Track Q) — Ledger export, yes/no on purpose.
- **O9** (due P4) — reversal dating: should a reversal post to the
  reversed entry's own date or today? (Long-standing open reflection;
  matters more once commitments cancel via reversals.)

## 11. Where the old files went

| File | Forward-looking content | Record-of-shipped content |
|---|---|---|
| `BACKLOG.md` | triaged into §§5–10 (every open item is now in a track, in Q, in Parked, or in the register) | Done log → git history (`git log`, and the file's own history) |
| `FORECAST.md` | §6 entire (with §9.1 decided as D2; §4B superseded) | none was shipped |
| `CUSTOM_REPORTS.md` | v2/v3 → S5, S7 | shipped v1 design → SPEC decision 25 |
| `IMPORT_WIZARD.md` | R4–R10 + rename → §7 | shipped phases/spine → SPEC decisions 23–24 |
| `UI_CONSISTENCY_AUDIT.md` | archetype end-state → §3.3 | archetype conventions → `docs/ARCHITECTURE.md` "Archetype conventions"; AS-IS inventory → git history |

Code comments that referenced those files were re-pointed in the same
change that deleted them.
