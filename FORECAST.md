# Forecasting, commitments, targets, and the project dimension — design sketch (not built)

**Status: not started.** No code, no migration, no route exists for any
of this yet. This document exists so the next session that picks this up
doesn't have to re-derive the reasoning from scratch — it's a design
sketch to build from, not a description of anything in the repo today.
Internal planning like `CUSTOM_REPORTS.md`/`BACKLOG.md`/
`UI_CONSISTENCY_AUDIT.md` — not in `mkdocs.yml`'s nav, not published to
`docs.postwarden.org`.

Origin: a 2026-08-31 planning conversation about the feature that makes
PostWarden worth using *instead of* cashflow-only tools rather than
alongside them: seeing expected future cashflows, and getting a yes/no
answer to "can I make this financial commitment?" — the thing YNAB users
mean when they say the app makes them "YNAB poor." The design was
stress-tested against a full wedding-planning scenario (§7), which is
also the acceptance test. The same conversation then surfaced a second,
larger question — whether PostWarden should grow an ERP-style **project
dimension** (§4A) — which reshapes part of this design and is the
gating open decision (§9.1).

`BACKLOG.md` items this document refines or supersedes for the in-app
version: "Report: Accounts Receivable and Accounts Payable management"
(absorbed into commitments, §3.1), "Payment reminder / scheduled
payments coming up widget" (§5.5), "Auto calculate journal entries for
loans" (a generator on top of commitments, §8 fast-follows), and
partially "New Report Option: income statement with months as columns,
future months have budget numbers" (the Projected Cash Flow report is
the cash-side sibling of that idea).

---

## 1. The core insight

YNAB's celebrated goal behavior is one division, recomputed live:

```
required_per_month = remaining ÷ months_left
```

Its magic is that "remaining" self-corrects when you pay. In PostWarden,
if a commitment is booked the double-entry-native way (Dr Expense /
Cr A/P at signing; Dr A/P / Cr Cash on each payment), **the liability
account's balance *is* the live "remaining"** — no parallel goal-
tracking bookkeeping, nothing to reconcile. The ledger already stores
strictly more information than YNAB keeps. What the schema cannot
currently hold is *when things come due* — the time dimension on
obligations — and what the app cannot currently do is *project* that
forward.

Therefore the whole feature is two additions and a principle:

1. **Due-date structure** on balances (commitments) and on goals
   (targets).
2. **A projection engine** that expands schedules, commitments, and
   budget lines into a future cash picture.
3. **The projection is a query, never a posting** — SPEC decision 10
   ("a simulated close is a query") applied to the future instead of the
   past. Never store a computed required payment; never post projected
   entries into `journal_entries`. Everything recomputes on read, which
   is precisely what makes it self-correcting for free.

The PostWarden equivalent of feeling "YNAB poor" is: *projected closing
cash goes below your buffer in some future month*. Same psychological
effect, derived from the ledger instead of envelope allocations — and
more honest, because it sees liabilities that cashflow-only tools
cannot.

## 2. What already exists (inventory, verified against `db/schema.sql`)

| Primitive | What it gives this feature | Gap |
|---|---|---|
| Scenarios, two shapes (SPEC decision 3) | Full scenarios already model "a dated hypothetical event… cash forecasting falls out for free" — the what-if overlay (§5.4) needs no new primitive. Income-statement-only scenarios hold budgets. | None — this is the payoff of scenario-as-a-dimension. |
| `budget_lines` (scenario × account × month, editable in place per decision 4) | The "budgeted outflows" stream of the projection; under §4A also the per-project budget planes. | Account-grained; no project dimension yet (§4A) and tags don't participate (deliberate — §4B). |
| `scheduled_entries` + lines (`interval_unit`/`interval_count`/`next_date`) | Recurring known transactions — the "scheduled" stream. | **No end condition**: schedules run forever, so they project to infinity. Needs nullable `end_date` and/or `remaining_occurrences`. Also they only *materialize* (into Staging, when due); nothing *projects* future occurrences virtually. |
| `accounts.is_cashflow` | Defines "cash" for the projection — same set the Cash Flow Statement uses. | None. |
| Tags (entry-grain, `is_active` soft-retire) | The only purpose/project-ish grouping today. | Entry-grain (a mixed entry can't be partially in-scope) and many-to-many (sums across tags double-count) — see §4A for why that matters. |
| `accounts.code TEXT CHECK ('^[0-9]{3,8}$')`, `accounts.is_active` | The chart-of-accounts governance answer under §4B: code space is effectively unbounded, retired branches disappear from pickers but keep history. | None. |
| Reversal machinery (`reverses_entry_id`) | Commitment cancellation (§5.6). | None. |

## 3. New objects

### 3.1 Commitments — due-date structure on a balance

A commitment attaches payment/receipt due dates to a balance-sheet
account's balance. Roughly:

- `commitments(id, account_id, description, target_id NULL, status, …)`
- `commitment_due_dates(commitment_id, due_date, amount NULL, refundable_until NULL)`
  — a payment plan; a single row with just a final due date is the
  minimal case ("the remaining balance is due by June 12").

Everything else is **derived, never stored**: remaining = the account's
balance; months left = from today to the last due date; required pace =
remaining ÷ months left; behind/on-track = required pace vs. original
pace.

**Commitments are symmetric — not hardcoded to liabilities.** "My
parents pledged $5,000, half in January" is A/R with due dates: book
Dr `A/R:Parents` / Cr contribution income, attach a commitment, and the
projection's *inflow* rows update exactly like a vendor's outflows do.
This one decision absorbs the backlog's A/R–A/P management item and the
original pass-through-lending complaint with the same primitive. It's a
schema-shape decision that is cheap now and a migration later — do it
from v1.

Lifecycle (`status`): `draft` (a saved quote/what-if — feeds the
affordability check but not the tracker's "committed" number) →
`active` → `closed` (paid off) or `cancelled` (reverse the booking
entry via the existing reversal machinery, in the same gesture).
`refundable_until` on payments lets the tracker report "of $13,100
paid+committed, $6,000 is still recoverable" — real peace of mind when
plans change. Lifecycle states beyond active/closed can ship as a
fast-follow (§8).

### 3.2 Targets — an envelope with a deadline

A target is a self-imposed goal: amount + deadline + a **scope** to
measure progress against. It exists *before* any contract does (you set
the wedding envelope before signing a single vendor), so it cannot
require a booked liability — this was an explicit reversal of an
earlier "liability-backed only" position, forced by the scenario in §7.

- `targets(id, name, amount, deadline, scope, buffer NULL, status)`
- **What "scope" is depends on §9.1, the gating decision.** If the
  project dimension (§4A) is adopted, scope is simply `project_id` —
  one kind, clean. If not, scope is polymorphic — a tag or an account
  subtree (§4B), with the tradeoffs documented there.
- Commitments link to a target via `commitments.target_id`.

Derived, never stored — three colors of money, the structural advantage
over YNAB (which only sees cash that left):

- **Paid** = actual postings in scope,
- **Committed** = balances of the target's linked commitment accounts
  (booked, cash not yet gone),
- **Unclaimed** = amount − paid − committed.

Two *independent* health checks, because there are two different ways to
be off track:

1. **Pace** (YNAB's recalc): (amount − paid) ÷ months left, vs. the
   original monthly pace.
2. **Solvency**: re-run the projection with actuals-to-date, assuming
   the full target amount still gets spent — does closing cash at the
   deadline still clear the buffer? Catches the sneaky failure where
   wedding pace is perfect but *life* overspent and eroded the
   projection the envelope was derived from. The target amount itself
   stays **fixed** (auto-shrinking it would hide the problem); the UI
   shows the solvency *margin trend* ("still affordable, margin down
   from $3,800 to $1,100").

Pace is per-target; **solvency is always global** — see §6.6 for why
that split is the design's most important line.

A `closed` target freezes its story instead of nagging forever; closing
one offers, in the same gesture, to retire its scope (the project, tag,
or branch) so retirement is the default path. Deadlines are editable —
venues fall through — and everything recomputes because it's all
queries.

### 3.3 The projection function

A set-returning function (working name `fn_projected_cash(from, to)`),
same philosophy as `fn_trial_balance`/`fn_cash_flow_lines`: callable
from the app, psql, or BI alike. It combines, **without materializing
anything**:

- opening cash: actual balance of `is_cashflow` accounts today;
- **scheduled** stream: virtual forward-expansion of active
  `scheduled_entries` recurrence rules (requires the end-condition
  columns, §2);
- **committed** stream: `commitment_due_dates` rows (explicit amounts,
  or remaining-balance ÷ remaining-due-dates when amounts are null);
- **budgeted** stream: `budget_lines` from a caller-chosen budget
  scenario — **summed across all project planes** if §4A is adopted
  (the plane separation is a budgeting/editing concept, not a cash
  concept; cash reality is the sum — §4A.3).

**Daily grain internally, monthly presentation.** Monthly closing cash
can look fine while Feb 3 (rent out, salary not in, deposit due) goes
negative — and wedding vendors love deposit due dates. Since schedules
and commitments carry real dates, project day by day and surface a
per-month **lowest point** (`low: $1,240 on Feb 3`) alongside the
close. Buffer checks run against the low, not the close. Build this in
from v1 — retrofitting grain into a projection function is painful.

**The double-counting precedence rule** (the one hard problem — decide
deliberately, don't discover it in QA): per (account, month),
**scheduled entries beat budget lines**. A schedule is a dated
fact-to-be; a budget number is a working assumption for accounts with
no better information. If both exist for an account-month, the budget
line is superseded (shown struck/grayed in the report, not silently
dropped). Commitments only ever touch cash + their own balance-sheet
account, so they collide with budgets only if the user budgets the
*payment* rather than the expense — a modeling error the report should
surface, not resolve. Under §4A the rule applies per (account, month,
project) — a wedding schedule supersedes the wedding plane's budget
line, never the General plane's. ⚠ Open decision (§9.4): confirm this
rule, and whether it needs a per-account override.

Deferred, but the projection should be written so it's addable:
credit-card settlement timing (an outflow paid by card in March leaves
cash in April — route card-paid legs through the card's settlement
date rather than treating all outflows as cash-immediate).

## 4. The scope question: two worlds

A temporary project (a wedding) shouldn't permanently colonize the CoA
or its code ranges. The accounting-sound framing: a chart of accounts
encodes the **nature** of a transaction; "wedding" is a **purpose** — a
project dimension. There are two ways to give purpose a home, and
choosing between them is the gating decision for targets (§9.1).

### 4A. The project dimension (the ERP move — recommended if the multi-year vision is real)

The same architectural move SPEC decision 3 already made once —
"scenario is a dimension, not a module (the OneStream model)" — applied
a second time.

**Schema:**

- `projects(id, code, name, color, is_active, notes)` — curated,
  small, soft-retired like tags and accounts. A project is *just an
  attribution key*: no amounts, no dates — money-planning lives on the
  target, and a project can exist for years without one.
- **`journal_lines.project_id`, nullable FK** — line grain, like every
  ERP. `NULL` = "general life," which is most lines forever. Also on
  `scheduled_entry_lines` and entry-template lines, so recurring
  entries stamp their occurrences automatically.
- `v_fact_lines` gains the column; the star schema gains a
  `dim_project` — Power BI slicing falls out for free.
- Optionally (the expensive half — §9.3): `budget_lines` grows the
  dimension: `(scenario, account, month, project)`.

**The property tags can't give: sums that partition.** Tags are
entry-grain and many-to-many — an entry can be `wedding` *and*
`tax-deductible`, which is what tags are for, but it means sums across
tags double-count, so "P&L by tag" is not an honest report. A project
is line-grain and **exactly zero-or-one per line**: every dollar
belongs to one project or to general life, project totals sum back to
the ledger total, and mixed entries split honestly at the line. That
partition property is what makes a dimension a *reporting axis* rather
than a label. Tags and projects coexist with clean roles — overlapping
descriptive labels vs. exclusive attribution — same as ERPs pair
attributes with dimensions.

**Pros:**

1. Dissolves nature-vs-purpose permanently — the CoA never hosts a
   purpose again; no wedding subtree, no retirement ritual, no code-
   range anxiety. §4B's whole tradeoff becomes a non-problem.
2. Simplifies this document's own design: target scope = `project_id`
   (no polymorphism), and with budget-by-project the envelope's
   sub-allocation becomes budget lines `(WEDDING × Catering × month)` —
   per-category planning against **natural** accounts, strictly better
   than either §4B style. §4B's "middle path" allocation-rows
   machinery dies unbuilt.
3. Line grain fixes the mixed-entry problem outright.
4. The future-proofing dimension: the wedding is the mild case — where
   this pattern really earns its keep is quasi-entity accounting (a
   rental property, a freelance side gig) slicing one ledger per
   venture without separate books.
5. Philosophically at home: "dimension, not module" and "if a number
   matters, it's computable by SQL alone" both already describe it.

**Cons / costs:**

1. **Blast radius.** Touches the fact table — the most protected object
   in the schema — plus `scheduled_entry_lines`, templates, the entry
   form, the import wizard (a new mappable target field;
   `IMPORT_WIZARD.md` §1.1's vocabulary grows), the CSV export/
   re-import round-trip, seed/demo data, and every report's filter
   bar. Each piece small; the sum is a real project. The nullable
   column itself is additive — append-only triggers and the 60
   invariant tests shouldn't notice it.
2. **The `budget_lines` PK change is the heavy half** and can be
   deferred (facts-only first), but deferring it defers pro #2.
3. **A third grouping mechanism.** Subtrees, tags, *and* projects means
   `docs/GUIDE.md` must teach roles crisply — nature → accounts;
   exclusive attribution → project; overlapping labels → tags — or
   users pick wrong and blame the app.
4. **Per-entry UX tax**, mitigated by progressive disclosure (§6.0)
   and payee defaulting (§6.2).
5. **An immutability carve-out** (⚠ §9.2): if you post a line and
   forget the project, is fixing it a reversal? Argument for no:
   `project_id` affects no balance, no trial balance, no statement —
   it's attribution metadata, like the entry header's description/
   reference, which decision 4 already makes editable on posted
   entries. So: editable-in-place, trigger-permitted — but it would be
   the first *line-level* field to get that treatment, and needs its
   own SPEC decision and careful wording.

#### 4A.3 Budget planes — exact semantics (pinned 2026-08-31)

With budget-by-project, a budget scenario's lines live in **planes**:
one per project, plus the **General plane** (`project_id IS NULL` —
your ordinary-life budget, exactly what today's grid holds).

- **The grid shows and edits exactly one plane at a time. Default =
  General**, so the day-one experience is unchanged. Project planes are
  reached via a switcher next to the scenario picker, and are
  typically sparse (only the accounts that project budgets).
- **There is deliberately no summed *editable* view.** If March Dining
  shows 550 (250 General + 300 wedding tastings) and the user types
  500, no rule can say which plane absorbs the −50 — a summed editable
  cell is ambiguous by construction. Every write targets the visible
  plane.
- **Reading is different: sums happen at read time.** An optional
  read-only "All (combined)" view is fine for review, and the
  projection (§3.3) always consumes the **sum of all planes** — "what
  actually leaves the account in March" is 550. Plane separation is an
  editing concept, not a cash concept.
- **Variance is per-plane and internally consistent**: wedding plane
  vs. actuals filtered `project = WEDDING`; General plane vs.
  `project IS NULL` actuals.

**Sequencing if adopted:** the dimension belongs *before* the personal
instance exists (it's exactly the rebuild-costing change `BACKLOG.md`'s
preamble warns about), and *before or with* targets (phase C in §8),
because it changes what a target's scope is — building §4B's
polymorphic targets first means designing the same feature twice.

### 4B. The fallback world: tag or subtree scope (no new dimension)

If §4A is rejected, targets get a polymorphic scope instead — a tag
*or* an account subtree — and the CoA-governance story below applies.
Everything in this subsection is superseded by §4A if adopted.

**The clutter/exhaustion fear is smaller than it looks:** codes are
`TEXT`, 3–8 digits — four-digit ranges are convention, not constraint;
a permanent `5900 Life Events` parent with five-digit children costs
nothing from the 5000–5899 space. And `accounts.is_active` hides a
retired branch from every picker while history and old reports stay
intact. A CoA is a living document; the wedding subtree is temporary in
your *pickers*, not in your history.

**The two scope styles:**

| | Tag scope | Subtree scope |
|---|---|---|
| CoA footprint | zero — expenses post to natural accounts, entries carry the tag | a branch you deactivate when done |
| Sub-allocation (per-category envelope) | ✗ — `budget_lines` are account-grained; **do not** add a tag dimension to them for this | ✓ — Budget Grid + Variance work as-is on the subtree's children |
| Lifetime nature-reports | seamless | a seam (wedding photography sits under Wedding, not Services) |
| Right for | small/fuzzy goals ("Japan trip under $4k") | project-sized efforts with sub-budgets you negotiate against |

Both are one grouping key in the target-measurement query — supporting
both is nearly free. Tag-grain caveat: `journal_entry_tags` is
entry-grain, so a mixed entry is all-or-nothing in a tag scope —
document the rule ("split mixed purchases into separate entries"),
don't add line-grain tags for this.

A possible later middle path (only in this world): one shallow leaf per
life event under a permanent parent, with sub-allocation as
planned-allocation rows on the target itself, matched to actuals by
payee or sub-tag. More new machinery; §4A does it better.

## 5. The user-facing surface

(World-neutral except where noted; §6 walks the same surfaces
concretely under §4A.)

### 5.1 Projected Cash Flow report (Range/period archetype)

Months as columns; rows grouped by stream so supersession (§3.3) is
visible:

| | Sep | Oct | … |
|---|---|---|---|
| Opening cash | | | |
| Scheduled inflows / outflows | | | |
| Committed inflows / outflows | | | |
| Budgeted income / expense | | | |
| **Projected closing cash** | | | |
| Lowest point (day) | | | |

Headline card: projected cash at range end, minus the buffer ⇒ "up to
$X is unclaimed by anything." Buffer ("never plan below $N") is a
user-level setting; targets can carry their own override. Under §4A the
committed/budgeted rows can optionally break down by project chip
(§6.6). ⚠ Open decision (§9.5): account-grain rows vs.
cash-totals-only in v1.

### 5.2 Planning mode

The tweak-until-satisfied loop is the whole point of the initial
planning phase, so the report needs an **editable planning mode**:
clone the operating budget into a working income-statement-only
scenario (budgets are editable in place by design — decision 4 — and
cloning is what makes tweaking safe), the budgeted rows become live
editable cells Budget-Grid-style, the headline recomputes per
keystroke. Under §4A, planning mode edits whichever plane it's pointed
at. "Commit this plan" promotes the clone to the operating budget and
creates the target in one gesture. Nothing posts to the journal at any
point — the entire exercise is queries over scenarios.

### 5.3 Target tracker (dashboard card + detail)

> **Wedding — $20,000 · 6 months left**
> ▓▓▓▓▓░░░░ Paid $4,100 · Committed $9,000 · Unclaimed $6,900
> Pace: planned ~$2,000/mo of wedding cash; averaging $1,370.
> To stay funded, remaining months need $2,320/mo. Projected June cash
> clears your buffer by $1,850. ✅

Both health checks (§3.2), amber when either trips, with the corrected
monthly number — the YNAB recalc, derived from the books. Under §4A the
detail view is the project cockpit (§6.4); under §4B-subtree,
per-category allocation vs. actual is the existing Budget Grid /
Variance on the subtree.

### 5.4 The affordability check ("Can I afford this?")

A dialog, launchable from the tracker or the report: amount, payment
schedule, which target it counts against. Three checks, in order:

1. **Category**: fits the sub-allocation? ("Band is $3,500 but Music
   has $1,500 — approve by pulling $2,000 from Flowers?") — reads the
   project plane under §4A, the subtree budget under §4B.
2. **Envelope**: fits the target's unclaimed?
3. **Cash timing**: overlay the payments on the projection — does any
   month's *low* breach the buffer? ("Fits your budget, but February
   dips $680 below buffer. Moving the deposit to March 15 clears it.")
   Always run **globally**, across every target and project at once
   (§6.6).

Verdict is green/yellow/red *with the reason and a suggestion*. "Yes"
converts the what-if into the real thing in one click: the booking
entry, the commitment with its due dates, linked to the target. Under
the hood the overlay is a `draft` commitment fed to the same projection
query. Arbitrary messier hypotheticals ("what if we also move
apartments in April?") are the existing full-forecast-scenario overlay
— no new primitive.

### 5.5 The app speaks first

Peace of mind requires surfacing problems unprompted: an
upcoming-payments dashboard widget (commitment due dates make the
existing backlog item real), and state-change alerts ("Feb low dropped
below buffer" the week it became true). Architectural caveat: this
deployment deliberately has no task runner (SPEC decision 9 —
`materialize_due_schedules()` is lazy). Lazy-on-request recomputation
of alert states gets most of the value; true push/email stays
backlogged with the other email features.

### 5.6 Optimism stays quarantined

Money you shouldn't plan on (cash gifts at the wedding) lives in an
optimistic full-forecast overlay scenario: visible as upside, excluded
from every yes/no verdict.

## 6. UX walkthrough under the project dimension

How §4A looks and feels, screen by screen, each mapped to its
`UI_CONSISTENCY_AUDIT.md` §1 archetype — nothing here invents a new
page shape except the cockpit (§6.4), which is assembled from existing
panels. Through-line: **one new concept (the project chip), visible in
exactly five places** — entry form, filter bars, cockpit, budget plane
switcher, projection breakdown.

### 6.0 Before any project exists: the app looks exactly like today

`project_id` is nullable and `projects` starts empty, so there is no
picker on the entry form, no filter chip, no dashboard card — zero new
load for the user who never touches this. The dimension materializes in
the UI only after the first project is created.

### 6.1 `/projects` — Management/CRUD archetype

Same list shape as Payees or Tags: code, name, accent color, status,
attributed-activity total; retire-don't-delete. "New project" asks for
almost nothing — it's an attribution key, not a plan; the target is
attached later from the project's own page. Each row opens the cockpit.
This roster is how multiple projects stay sane: one list, and a closed
project drops off pickers everywhere at once.

### 6.2 The entry form — one picker, two grains

Next to Scenario: **Project: [General ▾]**, defaulting every line; each
line's chip inherits and can be overridden. Set it once per entry 95%
of the time; the per-line override exists for the mixed-entry case
($180 Costco run: $120 groceries line General, $60 wedding-favors line
`WEDDING`) — honest attribution the entry-grain tag design could never
do. Two behaviors keep it effortless: **payee memory** (two entries to
"Alameda Venue Co." under `WEDDING` and the form pre-selects it for
that payee) and **schedules/templates carry the project**, stamping
every materialized occurrence on its way through Staging.

### 6.3 Journal (`/entries`) — Filterable transaction list archetype

One new filter control, same position on Journal and Staging alike:
**Project: [All | General only | …]**; rows show the project chip next
to tag badges. Two filters matter daily: **Project: Wedding** — the
complete wedding audit trail across every natural account; and
**Project: General only** (`project_id IS NULL`) — *your life without
the wedding*, the sleeper feature: "am I overspending on normal life?"
stops being a mental subtraction. The same filter on Income Statement /
Variance makes "life-only variance vs. life-only budget" first-class —
exactly the solvency question §3.2 cares about.

### 6.4 The project cockpit — the one genuinely new screen

Opening `WEDDING` lands where the whole story lives. Header = the
tracker card (§5.3) plus the affordability button. Below, three panels:

- **Allocation grid** — budget-by-project earning its keep: an
  Editable-grid-archetype table (a filtered Budget Grid, not a new
  component) showing only this project's plane — *natural* accounts
  down the side, wedding numbers in the cells, with Budgeted /
  Committed+Paid / Left per row and an *Unallocated* remainder line.
- **Commitments** — the vendor list with due dates (`A/P Venue —
  $6,000 due May 1 · $3,000 paid · refundable until Mar 1`), pledges
  on the A/R side showing as inflows.
- **Activity** — the Journal pre-filtered to this project.

Feel target: *everything about the wedding on one screen, and nothing
about the wedding required anywhere else* — CoA, General budget plane,
and normal reports stay as wedding-free as the day before the
engagement.

### 6.5 Budget Grid — planes

Exactly §4A.3: a plane switcher next to the scenario picker, default
General, edit one plane at a time, no summed editable view, optional
read-only combined view, projection consumes the sum.

### 6.6 Multiple projects — and where they must *not* be separate

Add `JAPAN27` (honeymoon, $4,000 by July 10): a second tracker card, a
second plane, a second chip color; the upcoming-payments widget
interleaves both projects' due dates. But the projection report does
**not** get a per-project version — the most important design line in
the feature: **projects partition attribution; they share one cash
reality.** There is one runway. The report stays global, with the
committed/budgeted stream rows optionally broken down by project chip
so you can see *whose* outflow causes a dip:

| | Feb |
|---|---|
| Committed out — `WEDDING` | −1,750 |
| Committed out — `JAPAN27` | −900 |
| Budgeted — General | −1,400 |
| **Closing / low** | 5,900 / **4,320 ⚠ Feb 12** |

Which produces the scenario that justifies the whole design: wedding
pace ✅, honeymoon pace ✅, *both cards individually green* — and the
global solvency check flags February anyway, because the flight deposit
and the band deposit land in the same tight month. **Per-project pace,
global solvency.** The affordability dialog asks "count against which
project?" for its envelope check, but its cash-timing check always runs
against everything at once. Tools that silo projects into separate
ledgers or spreadsheets cannot give you that interaction — it's the
single-repository argument applied to the future.

### 6.7 The ending

On the cockpit: **Close project** → one confirmation that closes the
target, retires the project (`is_active = FALSE`), and offers to
deactivate any project-specific tags in the same gesture. `WEDDING`
vanishes from every picker; the cockpit stays reachable from
`/projects` (filter: Closed) as a frozen retrospective — final cost vs.
the $20k plan, per category, forever queryable. The CoA never knew any
of it happened; in year ten the entry form's dropdown holds only what
you're actually doing in year ten.

### 6.8 The first-run path — onboarding is a projection prerequisite

(Surfaced by a blank-slate walkthrough: a newcomer who has never seen
PostWarden, guided from an empty instance to the affordability answer.)

The projection is only trustworthy once three things exist: **opening
balances**, **`is_cashflow` flags on the cash accounts**, and
**schedules for recurring reality** (a rough budget makes it better
still). None of today's onboarding asks for any of them, so a newcomer
who goes straight to Projected Cash Flow gets a confidently wrong
picture. That argues for a guided first-run path:

1. **Opening-balances step** — one entry: current balances of checking/
   savings/loans/cards against an Opening Balances equity account.
   This is also where "your car-loan spreadsheet becomes one line" —
   the moment the single-repository pitch lands.
2. **Flag the cash accounts** (`is_cashflow`) in the same breath —
   "which of these is money you can spend" — rather than leaving it as
   a setting to discover (the Cash Flow Statement already opts-in
   explicitly; the projection inherits that requirement).
3. **Schedule setup** — paycheck, rent, loan payments, subscriptions;
   loan payments introduce the principal/interest split as a benefit
   ("your net worth gets more honest every month"), not homework.
4. **Rough budget** — explicitly framed as a working assumption
   ("steal the averages from your spreadsheet, don't polish").
5. **Payoff screen: the runway** — end the flow on the Projected Cash
   Flow report showing their actual number, so setup has a visible
   reward.

The marketing insight buried in this: **no history import needed.**
The projection runs on today's balances plus forward-looking data —
history is optional garnish, not an onboarding cost. "Start with four
balances tonight, be projecting by bedtime" is a genuinely lower
barrier than history-import tools, and belongs in `README.md`'s pitch
and `docs/GUIDE.md`'s getting-started framing when this ships.

### 6.9 A UX bar: the whole flow works without saying "debit" or "credit"

The same walkthrough survived, end to end — opening balances, loan
payments, booking the venue, the affordability answer — phrased
entirely as "money from / money to" and "what you own / what you owe."
Write that down as the bar: **every screen in this feature must be
completable without the user needing double-entry vocabulary**, even
though the journal underneath is pure double-entry. Debits and credits
stay visible for the users who want them (the Journal shows the real
lines); they are never *required* to answer "can I afford this." Where
a form needs a counter-account, ask it in flow terms ("paid from
which account?"), not ledger terms.

## 7. The acceptance scenario (wedding walkthrough, condensed)

Engaged Aug 31, wedding June 12 (~10 salary cycles). Cash $12,400;
salary +$5,500/mo scheduled; rent + car loan −$2,250/mo
scheduled/committed; budget ~$1,400/mo variable.

1. **Sizing**: Projection today→June 12 reads $26,240 closing; minus
   $5,000 buffer ⇒ $21,240 unclaimed. Planning mode: cut Dining
   400→250, zero spring Travel, settle at $23,800 ⇒ commit a **$20,000
   target**, deadline June 12. Under §4A: create project `WEDDING`,
   scope the target to it, sub-allocate on its budget plane against
   natural accounts (Venue 9,000, Photo 2,500, Music 1,500, …); under
   §4B: scope to an `Expenses:Wedding` subtree and use the Budget Grid
   on its children.
2. **Booking**: venue signed ⇒ Dr the venue expense / Cr `A/P:Venue`
   9,000; commitment: 3,000 now, 6,000 due May. The May outflow
   appears in the projection the instant the contract is booked.
   Parents' pledge ⇒ A/R commitment, inflows land in January.
3. **Tracking**: card shows Paid 4,100 / Committed 9,000 / Unclaimed
   6,900; pace and solvency both green; life-only variance
   (§6.3's "General only" filter, or the subtree-complement view under
   §4B) answers "is the rest of life on plan."
4. **Band ($3,500: half Feb, half June) vs. DJ ($1,200 June)**: band —
   category check fails at Music 1,500 (offer reallocation), timing
   check flags Feb low $680 under buffer, suggests March 15. DJ —
   green/green/green. One click books the winner.
5. **After**: close the target/project (§6.7). Retrospective = variance
   over the scope. Pickers in year ten as clean as year one.

## 8. Implementation phases (each independently shippable)

Phases 1–2 are identical in both worlds — they don't care what a
target's scope is. The fork is only at the dimension and at targets.

**If §4A is adopted (recommended ordering):**

- **Phase A — the project dimension itself**: `projects` table,
  `journal_lines.project_id` (+ `scheduled_entry_lines`, templates),
  entry-form picker with per-line override and payee defaulting,
  Journal/Staging + report filters, chip rendering, `v_fact_lines` /
  `dim_project`, import-wizard target field, CSV export/re-import
  round-trip, seed/demo data. Its own shippable unit, useful with
  nothing else from this doc built.
- **Phase 1 — schedule end conditions + `fn_projected_cash`**: nullable
  `end_date`/`remaining_occurrences`; daily grain; precedence rule. No
  UI beyond maybe the upcoming-payments widget.
- **Phase 2 — Projected Cash Flow report + planning mode** (schedules +
  budget streams only; valuable with no commitments at all).
- **Phase C — commitments (symmetric) + project-scoped targets + the
  cockpit + affordability dialog** — the headline feature. Cockpit
  ships with allocation as a read-only summary if Phase D isn't done.
- **Phase D — budget planes** (`budget_lines` PK change + plane
  switcher, §4A.3) — when envelope sub-allocation is actually wanted;
  it's this change's first real customer.
- **Fast-follows**: what-if overlay UI, commitment lifecycle states +
  `refundable_until`, state-change alerts, credit-card settlement
  timing, the loan amortization generator, per-project chip breakdown
  rows on the projection, and the **guided first-run path** (§6.8 —
  natural home is right after Phase 2, since its payoff screen *is*
  the projection report).

**If §4A is rejected:** drop A and D; Phase C builds polymorphic
tag/subtree targets per §4B instead, sub-allocation via subtree Budget
Grid only.

Phases A, 1, C, D all touch `db/schema.sql` (⇒ Alembic migrations *and*
the raw-schema baseline). **Sequence the schema parts ahead of standing
up the personal instance**, or they cost a rebuild — same warning
`BACKLOG.md`'s preamble already makes, and doubly so for Phase A, which
touches the fact table.

## 9. Open decisions (deliberately unresolved — decide before building)

1. **Adopt the project dimension at all?** (§4A vs §4B) — the gating
   decision; it changes what a target's scope is, so it must be made
   before Phase C. Sketch author's recommendation: yes, if the
   multi-year whole-financial-life vision is real.
2. **The line-level immutability carve-out** (§4A cons #5): is
   `journal_lines.project_id` editable-in-place on posted lines
   (attribution metadata, like the header's description/reference) or
   immutable like everything else on a line (fix = reversal)? Needs
   its own SPEC decision either way.
3. **Budget-by-project timing** (§8 Phase D): planes from the start, or
   dimension-on-facts first with the cockpit's allocation grid arriving
   later?
4. **Precedence rule** (§3.3): schedule-beats-budget per (account,
   month[, project]) — confirm, and decide if a per-account override
   is needed, or if showing the superseded number is enough.
5. **Report grain in v1** (§5.1): cash totals + stream groups only, or
   account-level rows from the start?
6. **Sub-allocation shape in the §4B world only**: subtree-only first
   (free) vs. target allocation rows early so tag-scoped targets get
   categories. Moot under §4A.
7. **Where the buffer lives**: one user-level setting, per-target, or
   both (per-target overriding)?
8. **Commitment ↔ entry provenance**: does booking an entry from the
   affordability dialog record a link (like `scheduled_entry_id` does
   for schedules), or is the account linkage enough?

## 10. Doc impact when built

- `SPEC.md`: new numbered decisions — projection-is-a-query (extending
  decision 10's principle forward in time), commitments-are-symmetric,
  the precedence rule, and per §9.1 either project-is-a-dimension
  (with the §9.2 immutability carve-out and the §4A.3 plane semantics)
  or target-scope polymorphism.
- `docs/SCHEMA.md`: new tables, the projection function in the
  reporting-layer table, `dim_project`, ER diagram additions.
- `docs/ARCHITECTURE.md`: the new modules (projects, commitments,
  targets/cockpit) and where the cockpit sits relative to the five
  component archetypes.
- `UI_CONSISTENCY_AUDIT.md`: the project filter/chip is a new
  per-archetype control — plan it against every page in each archetype
  at once, per that file's own standing rule.
- `docs/GUIDE.md`: the nature-vs-purpose section — accounts vs.
  projects vs. tags roles (§4A cons #3); the "book the A/P at signing"
  pattern for real-world commitments.
- `README.md`: "What you get" gains the projection/targets bullet, and
  the pitch gains §6.8's "no history import needed — start from four
  balances tonight" framing; `docs/GUIDE.md`'s getting-started section
  follows the §6.8 first-run sequence.
- This file gains ✅/status markers per phase, `IMPORT_WIZARD.md`-style,
  once building starts.
