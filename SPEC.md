# PostWarden — design specification

## The single organizing idea

A general ledger is a set of facts (journal lines) constrained by one
invariant: within an entry, debits equal credits. Everything else —
statements, budgets, variance — is a *query over those facts*. PostWarden
therefore has exactly one write path (post an entry) and pushes every
invariant into PostgreSQL, so the set of facts can never be inconsistent
regardless of which client wrote them.

## Decisions and rationale

### 1. Signed amounts are canonical; debit/credit are derived

`journal_lines.amount` is signed: debit = positive, credit = negative.
The double-entry invariant becomes `SUM(amount) = 0` per entry — one number
to check, no pair of columns to keep consistent. `debit` and `credit` are
`GENERATED ALWAYS ... STORED` columns, so the familiar two-column
presentation exists everywhere (screens, views, BI) but *cannot* disagree
with the canonical amount. GnuCash's rational `value_num/value_denom` pairs
were rejected as BI-hostile; Actual's integer minor units were rejected
because `NUMERIC(18,2)` gives exact decimal arithmetic that SUMs natively
in SQL, DAX and Excel without a /100 convention.

### 2. The balance invariant lives in a deferred constraint trigger

A plain CHECK cannot see across rows. Application-level checks can be
bypassed by any other client — which is exactly GnuCash's architecture and
the failure mode to avoid. So PostWarden uses a `CONSTRAINT TRIGGER ... 
DEFERRABLE INITIALLY DEFERRED`: the app inserts header and lines inside one
transaction, and at COMMIT PostgreSQL re-derives `SUM(amount)` for every
touched entry. If it isn't zero (in an enforcing scenario), the commit
fails and the entire entry vanishes atomically. There is no code path
around this — not from the app, not from psql, not from a future importer.

### 3. Scenario is a dimension, not a module (the OneStream model) — with two shapes

`scenarios(code, scenario_type, enforce_balance, income_statement_only,
is_locked)` and every entry carries `scenario_id`. ACTUAL, a real
forecast, STAGING — all just tags on the same fact table, so comparing
any two of them is a `GROUP BY` with two `FILTER` clauses, never a
reconciliation between modules.

The first iteration of this decision let a non-ACTUAL scenario set
`enforce_balance = FALSE` and post single-sided planning lines —
"Groceries 6,000 in March," no counter-account — straight into
`journal_entries`, the same table as real postings. It worked, but it
was wrong: a monthly expense/income budget has no date that matters
within the month, no counter-account, and nothing to balance — it isn't
a transaction, hypothetical or otherwise, and shoehorning it into a
table whose entire reason to exist is "a transaction, verified balanced
at commit" meant either a confusing UI (a journal-entry form for
something with no journal-entry-shaped fields) or a footer tagline
("every entry balances, or it doesn't post") that was quietly no longer
true for a whole class of rows sitting right there in the Journal.

So a scenario is now one of two disjoint shapes, chosen at creation and
never mixed:

- **A full scenario** (`income_statement_only = FALSE` — ACTUAL, STAGING,
  or a real forecast/what-if actually modeling a dated hypothetical event
  like "what if I buy a house") posts to `journal_entries`/`journal_lines`
  exactly like ACTUAL always has, `enforce_balance` still deciding
  whether it must net to zero. A fully articulated forecast built this
  way is a projected P&L *and* balance sheet — credit Checking when you
  plan rent, cash forecasting falls out for free — because the event
  being modeled is genuinely transaction-shaped, just hypothetical.
- **An income-statement-only scenario** (a budget) never touches
  `journal_entries` at all — `fn_income_statement_only_guard` blocks it
  at the trigger level regardless of which client tries. Its numbers
  live in `budget_lines` instead: one row per (scenario, account, month),
  a plain amount, postable income/expense accounts only, no balance
  concept, editable in place rather than append-only (see decision 4 —
  a budget number is a working assumption, not an audit record, so the
  "reverse, never edit" discipline that matters for real postings has no
  reason to apply here). See `docs/SCHEMA.md` for the full guard-trigger
  list and the table comparing the two shapes side by side.

A CHECK constraint forbids ACTUAL from ever being `enforce_balance =
FALSE` or `income_statement_only = TRUE`. Locking a scenario (month-end
close, a budget you're done revising) blocks new entries/budget lines
via trigger either way.

### 4. History is append-only

Posted lines accept no UPDATE or DELETE (trigger-enforced); entry headers
allow editing only description and reference. Corrections are reversing
entries — `reverses_entry_id` links them, the UI offers one-click Reverse
and refuses to reverse twice. An audit trail you can't rewrite is worth
more than the convenience of editing, and it is how real books work.

### 5. Hierarchy with typed integrity

Accounts form a tree (`parent_id`). Only leaves (`is_postable`) accept
lines, so summary accounts are pure structure. Triggers enforce that a
child's `account_type` matches its parent's and that the tree stays
acyclic. `normal_side` (debit for assets/expenses, credit for
liabilities/equity/income) is derived in `v_dim_account`, never stored —
it is a function of type, so storing it would only create a chance for it
to be wrong.

### 6. The reporting layer is part of the schema

`v_fact_lines` (line-grain fact), `v_dim_account` (recursive path, depth,
normal side), `v_dim_date`, `v_monthly_activity` (account × month ×
scenario) form a star schema Power BI can consume without transformation.
`fn_trial_balance(scenario, as_of)` is a set-returning function — a
parameterized statement, callable from the app, psql, or BI alike. The
philosophy: if a number matters, it should be computable by SQL alone.

`v_dim_account.path` is the full breadcrumb including the account's own
name (e.g. "... : Housing & Utilities : Rent / Mortgage Interest") —
right for a picker/dropdown, where nothing else on the row names the
account. Every report row shows `account_name` next to it too, though,
so a second column, `parent_path`, carries the same breadcrumb with the
account's own name dropped off the end (`NULL` at the root). Rendering
`account_name` beside `path` instead reads as "Rent / Mortgage Interest
... : Rent / Mortgage Interest" — the leaf echoed back inside its own
path. `fn_rollup_balance`'s `path` output is `parent_path` under the
hood for the same reason (it backs Variance's rolled-up mode, which
renders it the same way); `fn_trial_balance`'s stays the full `path`,
since its only callers are the dashboard's own aggregation and the
`/api/*` JSON endpoints, neither of which pairs it with the name.

### 7. Thin application, no ORM

`db/schema.sql` is the single source of truth; the FastAPI layer composes
plain, explicit SQL through SQLAlchemy Core — no ORM identity map or
unit-of-work sitting between the app and the triggers that actually
enforce the invariants. Every query in the app can still be pasted into
psql. The journal entry screen is keyboard-first — account, debit *or*
credit, Tab, next line appears — with a live balance bar; the Post button
unlocks only when the entry balances (client courtesy; the database
re-checks at commit regardless).

### 8. Authentication is session-based and database-backed, not JWT

Every route requires a login; a session is an opaque random token in a
`sessions` table (`token`, `user_id`, `csrf_token`, `expires_at`), not a
signed/encrypted token like a JWT. The tradeoff: a DB round-trip on every
request instead of local verification — acceptable for a personal ledger's
traffic, and it buys real properties a signed token can't give you for
free. There's no signing secret to generate, store, or rotate, so there's
no class of bug where a leaked secret lets someone forge arbitrary
sessions. "Log out" or "log out everywhere" (e.g. on password reset) is a
`DELETE`, not a denylist you have to check separately. And who's logged
in, and for how long, is a query — consistent with every other "if it
matters, SQL should be able to answer it" decision in this schema.

Passwords are hashed with bcrypt in the app layer; the hash is the only
thing that ever reaches SQL. CSRF is a per-session token (the same
`sessions` row) rendered as a hidden field on every state-changing form
and checked with a constant-time compare — necessary the moment a session
cookie exists, since `SameSite=Lax` alone is a mitigation, not a guarantee.

`journal_entries.created_by_user_id` (nullable, `ON DELETE SET NULL`)
extends the existing audit-trail philosophy — history was already
append-only and reversal-only; this adds *who* posted or reversed each
entry, without requiring one (direct SQL/import inserts still work).

### 9. Scheduled entries land in Staging, not straight in the target scenario

A schedule (`scheduled_entries` + `scheduled_entry_lines`, a template
plus a recurrence rule) never posts directly to its
`target_scenario_id`. Each due occurrence first becomes a real
`journal_entries` row in the Staging scenario
(`materialize_due_schedules()`, run lazily on request rather than a real
cron — there's no task runner in this deployment); only once a human
approves it from the Staging page (`/staging`: checkboxes, select-all,
"Approve entries") does a *second* entry get posted into the real
target, linked back via `promoted_entry_id`. The alternative — post
straight to ACTUAL on the due date — would mean an entry appears in your
real books with nobody having looked at it, which defeats the point of
a personal ledger being something you trust without double-checking.

Staging is a real full scenario in every accounting respect
(`enforce_balance = TRUE`, every account type) — the one thing that
*is* special about it, `scenarios.is_staging`, is enforced at the
trigger level (`fn_staging_manual_entry_guard`), not left as an
application-layer convention: a Staging entry may only ever exist as the
output of one of its two automated producers — a schedule
(`scheduled_entry_id IS NOT NULL`) or a CSV import
(`import_batch_id IS NOT NULL`) — never typed in from New entry. This
was the one gap in an otherwise fully DB-enforced design — nothing
stopped a manual entry from landing in Staging and sitting there,
correct-looking but never reviewed, indistinguishable from a real
approved posting to a query that didn't know to check
`promoted_entry_id`. See `docs/SCHEMA.md`'s "Default scenarios" section
for the guard and the companion `uq_one_staging_scenario` index capping
this at one scenario, ever.

CSV import (`/import`) deliberately round-trips `/entries/export.csv`'s
own column layout rather than inventing a new one — export, edit in a
spreadsheet, re-import is then a real workflow, not a one-way dump. The
target scenario for a whole batch is chosen on the import form itself,
never read from a `Scenario` column inside the uploaded file: a CSV
someone hands you isn't a trusted source for "which scenario this
becomes real books in," the same reasoning that already put the target
on `scheduled_entries` rather than trusting a per-occurrence value.
Every group of rows is fully validated in Python before any of it
touches the database — a bad row is reported by its original line
number and simply never becomes a partial entry, rather than being
inserted and then rolled back.

### 10. A simulated close is a query, never a posting

Trial Balance defaults to showing Income/Expense accounts as
month-to-date only, with the gap to their true cumulative balance folded
into a synthetic "Retained Earnings" line under Equity — as if a monthly
close had actually run. It hasn't: this is computed at request time from
`fn_account_balances` called with two different date windows and
combined in Python (`trial_balance()`), and `raw=1` turns it off to show
the true unmodified cumulative balances instead. No closing entry is
ever posted, consistent with "if a number matters, it should be
computable by SQL alone" (decision 6) — closing the books for real would
mean a second write path outside the one the balance trigger governs,
which is exactly what decision 2 exists to prevent.

"Retained Earnings" itself is a real collapsible tree node — a parent
row (the combined figure) with "Current Year Earnings (Unclosed)" and
"Prior Year Earnings (Unclosed)" as its two children — not the two flat,
unrelated sibling rows this used to be. That distinction matters for
what `raw=1` means, and it means something different again on Balance
Sheet — see the addendum below.

**Addendum — the same idea, applied to individual lines instead of an
aggregate:** the Ledger (`/ledger`) reused this exact simulated-close
split once it grew its own "as of"/raw controls (previously fixed to
month-to-date with no such toggle at all). `ledger_rows()` applies the
same Income/Expense-vs-everything-else distinction at the level of
which journal lines are even fetched, rather than to a balance already
computed: Asset/Liability/Equity accounts always show every line from
inception through `as_of` (never closed, same as Trial Balance's
`full_balances`); Income/Expense accounts show only the as-of month's
own lines by default (same as Trial Balance's `merged_balances`), and
`raw=1` shows their full history too. Still no closing entry, same
reasoning as above — this is a WHERE-clause distinction on a read, not
a write path.

**Addendum — Balance Sheet's `raw` doesn't mean the same thing, and
that's deliberate:** Trial Balance already shows Income/Expense in their
own section, so `raw=1` there just relocates the same total P&L from a
synthetic Equity line back into the accounts that actually earned it —
nothing is lost, the figure is still on the page somewhere. Balance
Sheet has no Income/Expense section at all, so there's nowhere else for
that money to go: `raw=1` there means the "Retained Earnings" node is
simply *absent*, not collapsed into a single merged line the way an
earlier version of this feature did. That absence is intentional and
should be visible, not smoothed over — `balance_sheet()`'s `total_equity`
only adds the unclosed P&L back in when the plug is actually present, so
`raw=1` makes `total_assets` and `total_liab_and_equity` genuinely
disagree by exactly that amount, `in_balance` correctly comes back
`False`, and the Balance Sheet page says so (an explicit "won't balance
pre-close" note, plus the existing out-of-balance styling on the grand-
total row). This is not a bug to paper over with a plug under a
different name: a real balance sheet drawn up before a real close
genuinely doesn't balance against Assets alone, because Assets already
reflects a fiscal year's worth of transactions that Equity won't, until
something closes the books — which, per decision 2 and the rest of this
decision, PostWarden never does. Showing that gap honestly when asked to
("skip the simulated close") is more accurate than hiding it, not less.

### 11. Hierarchical rollups are built in the app, not SQL, and drill through uniformly

Trial Balance, Balance Sheet, and the Budget grid all show a summary
account's *rolled-up* subtotal (everything under it), not just its own
direct postings, with collapse/expand. `v_dim_account`'s recursive CTE
already gives every account its `path`/`depth` for free, but the rollup
itself (`domain/accounts.py`'s tree-building functions) is plain Python over
that flat list, not a second SQL recursion — the Budget grid needs to
merge *two* independent rollups (Budgeted from `budget_lines`, Actual
from `journal_lines`) node-for-node, which is awkward to express as one
SQL query but a straightforward tree walk once the balances are already
fetched. Every leaf amount that resulted from this rollup links through
to the Journal filtered to exactly what produced it (`account=` or,
on Payees, `payee=`), with a `back=` link returning to the report with
every filter it had applied still in place; a summary row's amount
stays plain text, deliberately, since no single Journal filter can mean
"everything under this node." See `docs/ARCHITECTURE.md` for the
mechanics (`useCollapsibleTree`, the `entry_link`/`cell_link` drill-
through pattern).

### 12. Presentation preferences live in the browser, not Postgres

Theme, money symbol/decimal/thousands formatting, cents-first amount
entry, and which tree rows are collapsed are all `localStorage`, keyed
per browser — never a column in `users` or anywhere else in the schema.
A personal single-user ledger has no "my preferences follow me to
another device" requirement, and keeping this out of Postgres means the
schema stays exactly as large as the accounting actually requires — a
theme name has no business being join-adjacent to a journal line.

### 13. Migrations are numbered SQL files, not an ORM framework

`schema.sql` was the only version of the schema that ever existed for a
long time, applied once by Postgres on a fresh volume — fine while the
only database anyone ran this against was the maintainer's own, freely
wiped with `docker compose down -v`. That stopped being fine the moment
self-hosting other people's real financial data became the point: a
self-hoster who pulls a schema change has no way to apply it to their
*existing* database at all, and "wipe it and start over" is not a
sentence anyone should read about their own ledger.

Rejected: an ORM-based migration framework (Alembic and equivalents).
That's the standard answer, but it's the wrong one here specifically —
decision 7 already rejected an ORM for the query layer on the grounds
that `db/schema.sql` should stay something you can read, run in `psql`,
or hand to Power BI directly; pulling one in just for migrations,
generating Python-side revision graphs over a schema that's supposed to
be plain SQL, undoes exactly what decision 7 was for.

Also rejected: timestamp-prefixed migration filenames (Rails/Django's
convention, e.g. `20260826120000_add_thing.sql`). That convention exists
to avoid collisions when multiple branches add migrations concurrently
and merge later — a real concern for a team repo, not for one that's
effectively single-branch, single-maintainer-authored so far. Sequential
integers (`001_`, `002_`, ...) are more readable and sort in the order
they were actually meant to run, with no collision risk worth paying for
here.

What shipped first: `db/migrations/NNN_description.sql`, forward-only
(matching decision 4's own append-only ethos — a bad migration gets
fixed by a new one, never edited or rolled back), applied by a
hand-rolled runner once at every app startup, tracked by a one-row
`schema_version` table.

**Superseded: this is now Alembic.** The rejection above held only as
long as every real deployment's database was disposable — freely
wiped with `docker compose down -v` — which stopped being true once a
personal or self-hosted instance could hold real financial data worth
keeping. At that point Alembic's actual cost (a Python-side revision
graph on top of a schema meant to stay plain SQL) is worth paying for a
migration runner that's been solved once, correctly, rather than
maintained by hand indefinitely. `schema.sql` keeps its role unchanged
— the full current state for a fresh install, and Alembic's baseline
revision — so decision 7's "every query in the app can be pasted into
psql" still holds for the schema itself; only the migration *runner*
changed. See `alembic/` and `docs/ARCHITECTURE.md`.

### 14. BI tools get their own read-only role, not the app's login

Decision 6 made the reporting layer part of the schema; in practice
"connect Power BI" meant handing someone the app's own `postwarden`/`postwarden`
Postgres credentials, because that was the only role that existed. That's
a bigger grant than the use case needs — a BI connection string has no
reason to be able to `INSERT` a journal line, `UPDATE` a locked scenario,
or `SELECT users.password_hash` (which `v_fact_lines` joins through for
`posted_by`, so the base table sits one hop away from anything with
`SELECT * FROM information_schema` curiosity) — and it's the credential
most likely to end up somewhere less careful than the app's own login:
pasted into a Power BI data source, a `.pbids` file, a colleague's laptop
if the ledger ever stopped being personal.

Rejected: generating a random per-instance BI password at first boot, the
way `POSTWARDEN_ADMIN_PASSWORD` works for the app's own admin user. That's a
real option and arguably the more correct one, but it needs a place to
persist the generated value so the Settings page can keep showing it
later — either a table (schema growth for a value that's really "the
Postgres role's own password, restated"), or re-deriving it from
Postgres each time (`ALTER ROLE ... PASSWORD` is one-way; Postgres itself
can't hand a password back out). `POSTWARDEN_ADMIN_PASSWORD` avoids this
because the app hashes it into `users.password_hash` once and never needs
the plaintext again. A BI role's password has no such hash to fall back
on — psql, Power BI, and Excel all need the plaintext every time. Given
that, a fixed default (`postwarden_bi`/`postwarden_bi`) matching the existing
`postwarden`/`postwarden` tradeoff is at least consistent, and the Connect Power BI
page (and README, and `deploy/gcp/README.md`) say the same thing that
page already says about the app's own login: change it with `ALTER ROLE`
before widening Postgres's bind address past `127.0.0.1`.

What shipped: `db/schema.sql` creates `postwarden_bi` (`LOGIN`, guarded by
a `pg_roles` existence check since `CREATE ROLE` has no `IF NOT EXISTS` —
this ships straight in `schema.sql` rather than as a numbered migration
per the "migrations are on the shelf for now" policy in `CLAUDE.md`) and
grants it `SELECT` on the four `v_*` reporting views and `EXECUTE` on
`fn_trial_balance` — nothing else. Settings →
Connect Power BI / Excel (`docs/ARCHITECTURE.md`'s Settings row) shows the
resulting host/port/database/login live, plus a downloadable `.pbids` so
Power BI Desktop opens pre-pointed at the right server without anyone
retyping it.

### 15. A pending Staging entry is exempt from append-only, until it's approved

Decision 4 made history append-only — posted lines take no UPDATE/DELETE,
entry headers only description/reference — on the grounds that an audit
trail worth having is one you can't rewrite. That argument is about
*history*: something a real books-keeping decision has already relied
on. An entry still sitting in Staging, proposed by a schedule or an
import and not yet approved, isn't that yet — nothing has relied on it,
and "reject" or "edit before approving" are exactly what a review queue
is supposed to let you do with a draft. Treating a Staging entry as
immutable from the moment it's created answered a question nobody was
asking, and left rejecting a mistake with no better option than leaving
it sitting in the list forever (there was no delete route for it at
all) or approving it anyway and reversing the result — reversal is for
undoing a real posting, not for declining a proposal that never should
have posted in the first place.

The exception, scoped as tightly as the condition that already
distinguishes "still pending" from "resolved" (`journal_entries.
promoted_entry_id IS NULL`) plus `scenarios.is_staging`:

- A pending Staging entry's lines may be DELETEd (never UPDATEd in
  place — editing a line is delete-then-reinsert through the app's own
  Staging edit screen, one rule instead of a matrix of which columns
  are safe to touch mid-flight). Lines can be added freely either way —
  INSERT was never restricted by entry maturity to begin with.
- The entry itself may be DELETEd outright (Staging's "reject" — gone
  for good, correctly not modeled as a reversal, since it was never a
  real posting), and its date/description/reference/payee may be
  UPDATEd. Its scenario and provenance
  (`scheduled_entry_id`/`import_batch_id`/`reverses_entry_id`) may not
  change under any circumstances — those aren't drafting details, they're
  what the entry *is* and where it's headed.

The instant `promoted_entry_id` gets set (Staging's own Approve action),
both exceptions vanish — from that point on a Staging entry is exactly
as immutable as anything posted directly, no different treatment at all.
Every other kind of entry (ACTUAL, a forecast, anything already
approved) is entirely unaffected; the trigger functions
(`fn_lines_immutable`, `fn_entries_guard` — see `docs/SCHEMA.md`) check
this condition first and fall through to the original, unchanged
behavior for everything else.

### 16. Tags are mutable on any entry — append-only never applied to them

Decision 4's append-only rule is about *what happened*: an amount, an
account, a date, once posted, can't quietly become a different amount,
account, or date without a paper trail (Reverse) showing the change.
A tag was never part of that claim. It's metadata about how an entry is
organized, not a fact about the transaction — adding "groceries" to a
five-year-old entry doesn't change what got bought or what it cost, it
just makes that entry findable under a category that didn't exist yet
when it posted. Treating tags as append-only right alongside amounts
and accounts would mean a tagging scheme could only ever apply to
entries created after the scheme was thought up — every entry that
predates a new tag stays permanently unorganized under it, for no
integrity reason at all.

`journal_entry_tags` (see `docs/SCHEMA.md`) has never carried an
immutability trigger, on any entry, posted or pending — this decision
just writes down why that's correct rather than an oversight. The
Journal's bulk **Edit tags** (`/entries/tags` — see
`docs/ARCHITECTURE.md`) adds to or removes from this junction table on
entries in any scenario, including ACTUAL, freely. What stays exactly
as immutable as before: `journal_entries`' own columns (amount lives on
`journal_lines`, never touched here) and every line — an entry's tags
can change; what it actually posted cannot, and this decision doesn't
touch that boundary at all. `journal_entries.description` is the one
column-level exception, covered already by decision 4's original
carve-out (reference and description), extended by the Journal's own
inline edit — a typo fix, same reasoning as a tag: organizational, not
a fact about the transaction, and equally worth being able to fix on
something already posted.

**Addendum — `journal_lines.memo` gets the identical carve-out, at the
trigger level rather than just the app layer.** Before this, a line's
memo was set once at posting time and then genuinely frozen —
`fn_lines_immutable` raised on *any* UPDATE, full stop, no exception
for Staging or anything else. That was tighter than the actual
rationale justified: a memo is exactly the kind of note-to-self a tag
is ("annual renewal, not the usual monthly charge"), attached to one
leg instead of the whole entry, but organizational for the identical
reason — it doesn't say what happened, only how to remember or file it.
There was no principled argument for tags being editable everywhere and
memo being editable nowhere; it just hadn't been asked for yet.

The exception is scoped at `fn_lines_immutable` itself, not merely by
which routes the app happens to expose: an UPDATE is allowed only when
`entry_id`, `line_no`, `account_id`, and `amount` all stay exactly
equal to their old values, `memo` the sole column actually free to
change — enforced regardless of which client sends the UPDATE, same
"push it into Postgres, not just app code" philosophy as every other
integrity rule here (decision 2). Unlike tags, this needed a schema
change (a trigger-function edit, not a new column) rather than being
already-shipped scaffolding waiting for a UI — `db/schema.sql`'s own
comment on integrity trigger 3 has the full before/after. The Journal's
click-to-edit on each line's memo (`/entries/lines/{id}/edit-memo`,
`docs/ARCHITECTURE.md`) is the one route that exercises it.

### 17. Entry ids are a random 6-character code, not a sequential integer

Every other table in this schema uses a plain `BIGINT GENERATED ALWAYS
AS IDENTITY` — the obvious default, and correct for anything nobody's
expected to read as a sequence. `journal_entries.id` was the same until
this decision, and it had a real problem once Staging entered the
picture: a pending Staging row draws from the *same* id sequence as a
real posted entry (it's the same table — see decision 15), and
rejecting one deletes it outright. A ledger that's posted entries
`#21` and `#23` with no `#22` anywhere looks broken even though nothing
actually is — `#22` was a schedule occurrence or an import row someone
correctly rejected, and its number is gone for good. There was no way
to explain that gap to someone just reading their own Journal.

A sequential id also implied something it never actually promised:
"higher number = posted later" is true only until the first rejected
Staging row breaks it, and reordering an entire population of ids to
close a gap after the fact isn't something you can do to a live ledger
without renumbering everything downstream of it.

The fix isn't to give Staging its own id sequence — that reintroduces
exactly the two-tables-pretending-to-be-one shape decision 15
deliberately avoided, just moved into the id column instead of a
second table. Instead, `id` is now a random 6-character code from
`fn_generate_entry_id()` (uppercase A-Z and 0-9, retried on the rare
collision — 36⁶ ≈ 2.18 billion possible codes, comfortably more than a
personal ledger will ever approach): nothing about it implies a
complete, gapless sequence, so a Staging entry's id being consumed and
never appearing anywhere a person looks isn't confusing the way a
missing sequential number was. `reverses_entry_id`, `promoted_entry_id`,
`journal_lines.entry_id`, and `journal_entry_tags.entry_id` all follow
suit (`TEXT`, matching `id`'s own type) — no other column on any other
table changes.

One thing a sequential id gave away for free that a random one can't:
same-day ordering. `ORDER BY entry_date, id` used to mean "and within a
day, in the order they were actually posted" as a side effect of id
being monotonic. A random id carries no such order, so `journal_entries`
now also has `seq` — a plain identity column, exactly what `id` used to
be, except it's never displayed, never referenced outside an `ORDER BY`,
and exists for that one purpose alone. It isn't `created_at` doing this
job: Postgres fixes `now()` once per *transaction*, not per statement,
so a batch of entries inserted together (a schedule materializing
several occurrences, an import, even a test fixture building several
entries before committing) can share one identical timestamp — `seq`
can't, by construction, since a plain identity column advances on every
row regardless of how many share a transaction.

### 18. Payees and tags get a real Delete, alongside — not instead of — their existing soft states

Payees already had `is_active` (decision: never written down as its own
numbered entry, just the schema's own comment on `payees` — "hide this
from future pickers, keep it on everything it's already posted to").
Tags never had any lifecycle state at all — decision 16 already
established they're organizational, freely re-attachable metadata. Both
pages (`/payees`, `/tags` — see `docs/ARCHITECTURE.md`) now also offer a
real **Delete**, and the natural question is why that isn't simply what
Archive/deactivate already meant, or why Delete didn't just replace it.

It isn't the same operation. Archiving a payee removes it from the New
entry/Scheduled/Staging pickers *going forward* while leaving every
past entry that used it completely untouched, name and all — the
"Whole Foods" on a receipt from two years ago stays "Whole Foods"
whether or not you still shop there. Delete is a different claim
entirely: "this row shouldn't exist," full stop — every entry that
referenced it loses the label (`payees`'s FKs are `ON DELETE SET NULL`;
a tag's junction rows are `ON DELETE CASCADE`, decision 16's own
mechanism). Collapsing those into one button would force a choice
neither actually wants: keep Archive-only and there's no way to undo a
payee created by typo or genuinely walk away from a mis-tag; make
Delete the only option and "I don't use this vendor anymore" starts
quietly editing history it was never meant to touch. Payees and tags
both keep Archive/Unarchive *and* Delete now, each doing the one thing
its name promises.

Tags originally shipped with Delete only — the reasoning above held
that a tag has no equivalent "hide from future pickers" need, since a
tag with zero remaining uses (decision 16) isn't cluttering anything.
That missed where the actual clutter lives: not an entry's own tag
badges (which only ever show what's really attached), but the tag-input
widget's *suggestion list* (`all_tags()`) — every tag ever created shows
up there forever, whether or not it's still a category worth reaching
for, the same clutter problem the New entry payee combobox already had
before payees got `is_active`. Tags now carry the identical column
`payees` does, filtered out of `all_tags()` the same way
`quick_create_payee` already filters payees, and `_sync_tags()`/
`_add_tag_to_entries()` reactivate an archived tag on reuse the same
way `quick_create_payee` reactivates a payee — typing an old tag's name
back into an entry is exactly the same "back in use" signal either way.

**Merge** is the other new piece, on both pages: fold two or more
selected rows into one. The alternative considered — auto-picking the
survivor's name (e.g. whichever has the most entries, or the
alphabetically-first) — was rejected because a merge is usually
prompted by realizing two names are the *same real thing under
different spellings* ("Trader Joe's" vs "Trader Joes"), and neither
existing spelling is necessarily the one worth keeping; the UI (see
`MergeDialog` in `docs/ARCHITECTURE.md`) instead prompts for the
final name outright, pre-filled with the first selected row's name as
a sensible default but freely editable, covering "merge and clean up
the name" in one step instead of two. The surviving *row* (as opposed
to name) is arbitrarily the first one selected — its id is what every
foreign key gets repointed to — since which physical row survives is
invisible to the user the moment its name is set explicitly regardless;
only the merged-away rows' ids need to disappear, and any of the
selected ids would have worked equally well as the keeper.

### 19. Split (multiple periods at once) is Income Statement-only, and clips rather than snaps

Income Statement's `split` param (Monthly/Quarterly/Yearly) turns the
single date range into a matrix — one column group per calendar period.
Two decisions worth writing down, since both had a real alternative on
the table.

**Scoped to Income Statement, not Variance or Budget Grid too.** The
request that prompted this named all three (they're the reports that
share a % variance column, per decision-adjacent `pct_of_base`
machinery in `docs/ARCHITECTURE.md`), but only Income Statement is
actually built around a date *range* — Variance takes a single `as_of`
date (a snapshot, the same shape as Balance Sheet), and Budget Grid
already steps one calendar month at a time via its own prev/next links.
Neither has a range to split without first redesigning its own filter
model into something range-shaped, which is a different, larger piece
of work than "add a Split dropdown" — out of scope here, and not
something this decision tries to pre-judge the shape of. If either
report gets a range-based filter later, extending Split to it is a
separate, later decision.

**A partial edge period clips to the requested range; it never snaps
outward to a whole calendar period.** A custom range like Aug 15–Oct 3
split Quarterly could reasonably mean either: (a) Q3's column only
totals Aug 15–Sep 30 (what was actually asked for) and Q4's only totals
Oct 1–3, both labeled as partial: or (b) expand the effective range so
every column is a full calendar quarter, pulling in Jul 1–14 and Oct
4–whatever even though From/To never asked for them. (b) was rejected —
a report silently including dates outside what its own filter bar says
is a worse failure mode than a column whose total looks smaller than a
full quarter's, and the same "never show something the filter didn't
ask for" instinct already governs every other report's date handling in
this app. (a) means a period's own label ("2026-Q3") can outlive being
literally true for that column's contents, so the template shows the
real covered span alongside it whenever a period is partial, rather
than let the calendar-period name imply a full quarter's worth of data
that isn't actually there.

Implementation-wise, `_income_statement_matrix()` (see
`docs/ARCHITECTURE.md`'s own Split section) is a thin wrapper around the
existing single-range `_income_statement_rows()` — one call per period —
rather than a parallel matrix-shaped calculation. The alternative (a
second computation path that queries every period's balances in one
pass) would likely be marginally faster at a large period count, but
duplicates every rule the single-range function already gets right
(zero-balance rollup, the income/expense sign flip, the `pct_of_base`
convention toggle, income-statement-only/budget-scenario handling) —
personal-ledger scale never makes N+1 queries-per-period a real cost,
so there was nothing to trade the duplication for.

**Addendum — the trailing Totals column's label is rewritten client-side,
not threaded through the backend.** Split gained a whole-range Totals
column after the periods (a plain aggregate, same figures the unsplit
report would show), and the natural ask was for its header to read
whatever the Period dropdown currently says — "This Quarter", "Custom
range" — instead of a bare "Total". The dropdown's *choice* only exists
client-side, though (`widgets/periodPresets.ts`'s own comment: "the
backend only ever sees plain date_from/date_to" — a deliberate
boundary, predating Split, that keeps the preset a convenience rather
than a piece of state the server has to track). Making the Totals
header say "This Quarter" server-side would mean submitting the preset
as a real field and threading it through the route, back-links, and CSV
export — undoing that boundary for the sake of one label. Instead,
`PeriodPresetPicker` (which already fully owns preset↔date-range
translation) rewrites the header text itself, on load and on change,
the same place that already knows the answer. The default served by the
backend stays the plain, always-correct "Total" — what CSV export uses
unconditionally, since a CSV file
has no script to run.

**Addendum — Average is Totals divided by the period count, not a
fresh computation.** The alternative considered was giving Average its
own machinery — a third "combined activity" tree, or a per-row
averaging pass independent of how Totals gets built — on the theory
that an average conceptually is its own thing, not just Totals scaled
down. That's true in general, but not here specifically: Split's own
periods are contiguous and non-overlapping by construction (`_split_
periods` clips them to partition `[date_from, date_to]` exactly, no
gaps or double-counted days), which makes Totals.base_net for any
account *identically equal* to the sum of that account's base_net
across every real period — not approximately, not "close enough for
a report," genuinely the same number arrived at two different ways.
Once that holds, Average = Totals / n is exact, and every percentage
field (`pct_variance`, `*_pct_of_income`, ...) turns out to be
scale-invariant on top of that — a ratio of two amounts is unchanged
by dividing both by the same n, so those fields don't even need
recomputing, only copying through. Building Average as a real second
computation would have reproduced the exact same numbers through a
longer path, for no benefit; the one thing worth being careful about
(and worth this addendum) is that this equivalence depends specifically
on periods never overlapping — if Split ever grows a mode where periods
could overlap (unlikely, but worth flagging for whoever touches this
next), Average would need to go back to being computed independently
rather than derived from Totals this way.

**Addendum — Totals and Average are visually distinguished from the
real periods, and from each other.** Once a report has two kinds of
column — a period's own real figures, and an aggregate across all of
them — reading the header text is the only way to tell them apart at a
glance, and that's easy to miss while scanning a wide table. Both
aggregate columns get a shared "this is not a real period" treatment
(bold text, a tinted background derived from the theme's own rule
color via `color-mix()` rather than a fixed hex, so it stays correct
across every theme this app ships); Average additionally gets italic on
top, so the two aggregates don't read as one undifferentiated block
either. The alternative — a written annotation instead of a formatting
change (e.g., "(avg)" appended to the label) — was available but
formatting was what was actually asked for, and reads faster at a
glance than parsing extra text in an already-dense header.

### 20. Cash Flow Statement: cash is a per-account flag, exclusion is "all legs cash-tagged," and attribution needs no guessing

`accounts.is_cashflow` marks which leaf accounts are spendable cash
(checking, savings, physical cash) rather than deriving it from
`account_type` — several `asset` accounts (Brokerage, Retirement) are
deliberately *not* cash, and the boundary is genuinely a personal
editorial choice (does a brokerage sweep account count?), not something
`account_type: asset` can answer on its own. Default `FALSE`; `db/seed.sql`
opts in exactly the three liquid-cash leaves it ships.

**Exclusion is "every leg on the transaction is cash-tagged," not "legs
net to zero."** A pairwise-zero check is the natural first instinct and
is wrong on a 3+-leg entry that's still a pure internal reallocation —
checking splitting into savings *and* physical cash in one entry has no
pair that nets to zero, only the whole entry does. `fn_cash_flow_lines`
(`db/schema.sql`) computes `n_noncash` per transaction and excludes
anything where it's zero; `tests/test_cashflow.py` has a dedicated test
for the 3-leg case specifically, not just the 2-leg one a pairwise
implementation would already pass.

**Attribution is one formula, not three branches keyed on leg count —
and it's each leg's own signed amount, not a proportional share.**
The feature request described three shapes (1 cash/1 non-cash, 1
cash/N non-cash, N cash/N non-cash) as needing different handling, and
its own wording for the split case ("attribute proportionally by each
non-cash leg's share of the total non-cash amount") reads as literal
proportional redistribution. An early implementation built exactly
that: `cash_net * ABS(leg amount) / total_noncash_abs`, plus a
largest-remainder rounding pass so a split's shares always summed back
to `cash_net` exactly. It shipped, passed every test written against
it, and was wrong — caught in manual review against the demo seed data,
on the one shape that formula quietly mishandles: a transaction whose
non-cash legs don't all share one sign. Gross-to-net payroll is the
real instance (`Dr Cash 16,500.00, Dr Income Tax Expense 3,000.00, Dr
Payroll Tax Expense 1,500.00, Cr Salary Income 21,000.00`) — the
proportional formula bled part of the salary inflow onto the tax legs
by weight, showing withheld tax as if it were separate cash that had
arrived, and Salary itself as a blended net-ish figure that was neither
gross nor net.

The actual, much simpler rule: **each non-cash leg's contribution to
the cash change is its own posted amount, sign-flipped — no weighting,
no division, no rounding step at all.** A balanced entry means
`SUM(all legs) = 0`, so `SUM(cash legs) = -SUM(non-cash legs)` always,
for every leg-count shape alike; each non-cash leg's own amount is
already that identity's exact, already-two-decimal contribution. This
coincides exactly with the proportional formula's output whenever every
non-cash leg shares one sign (the common "split one purchase two ways"
case the request was written around — that's *why* the bug shipped
past that formula's own tests unnoticed), which is also why it took a
mixed-sign real transaction, not a synthetic split, to surface it.
Under the fixed rule the payroll entry reads Salary Income `+21,000.00`
(gross, its own true amount), Income Tax `-3,000.00`, Payroll Tax
`-1,500.00` — three honest lines that sum to the real `+16,500.00` cash
effect, rather than three numbers each a little wrong in a way that
happened to cancel out in aggregate.

A second, tempting fix was floated and rejected: attribute the *entire*
cash leg to the one non-cash leg whose sign differs from the others
(Salary, here) and drop every same-signed leg (the taxes) from the
statement outright, on the theory that money withheld before it became
cash was never really a "flow" in either direction. That collapses
cleanly for payroll, but breaks on a structurally identical shape: a
purchase partly covered by store credit or a same-entry refund —
`Dr Shopping 100.00, Cr Store Credit 33.33, Cr Checking 66.67`. The
same rule would show `Shopping: -66.67` and silently drop the $33.33
credit, hiding that $100 was actually spent and a third of it came from
credit rather than cash — a real loss of information, not a
simplification. There is no mechanical signal (leg count, sign,
`account_type`) that tells "this leg is a real destination" apart from
"this leg is a pre-cash reduction" in general; that's a judgment about
what the *account itself* means, which the ledger doesn't encode, and
the sign-flip rule sidesteps needing to make that judgment at all by
never discarding a leg. It also matches this project's own stated
intent for the Taxes accounts specifically — `db/seed.sql`'s comment on
account `7000` says they're "isolated so 'actual spendable income' is a
real number instead of buried in a paycheck," i.e. visible on their own,
not folded back into Salary.

One consequence worth being explicit about: **the "N cash legs, N
non-cash legs" case the request flagged as needing manual review isn't
actually a guess**, and neither is `N` cash legs/`1` non-cash leg (a
shape the request's own three-way split didn't name at all, and needed
no special case here). The balanced-entry identity above is exact
regardless of how many cash legs a transaction has — it only ever
depends on each non-cash leg's own amount. The request explicitly asked
for a manual-review flag on multi-cash-leg transactions anyway — that
ask is honored (`n_cash_legs` rides along on every row so the app can
flag it), as a "worth a glance" surfacing, not because the number is
less trustworthy than any other row's.

**The three-way tie-out is a real second (and third) computation, not
the same number read back three ways.** Statement total and net
cash-leg activity post-exclusion are mathematically guaranteed equal by
the sign-flip identity above (trivially now — no rounding algorithm has
to get it right, it's true by construction) — but the balance-sheet
roll-forward (ending minus beginning balance across `is_cashflow`
accounts, via `fn_account_balances`) is independent of
`fn_cash_flow_lines` entirely, computed straight from account balances
the way a Balance Sheet run twice would be. A mismatch there means
something `fn_cash_flow_lines` itself can't see going wrong — schema
drift, a data problem outside this feature's own code path — which is
exactly the failure mode the check exists to catch. Worth being
precise about what it *can't* catch, since it's easy to overstate: it's
a check on the **net** total (inflows + outflows together), not on
inflows or outflows individually — the gross-to-net bug above never
tripped it, in either its broken or fixed form, because misattributing
which contra-account a dollar belongs to never changes the aggregate
net change in cash, only how it's broken out. The tie-out catches lost
or duplicated money; it was never going to catch a same-total
misattribution between rows, and nothing about fixing that bug changed
what the check can see. It surfaces as a `.flash-warn` banner (the
report still renders; this is "look at this," not "something crashed,"
same posture as every other amber banner in this app) and one
`logger.error()` call — the first thing in this codebase to use
Python's `logging` module, since nothing before this needed to log
anything the app itself didn't already show on screen.

**Date range is inclusive on both ends, not the half-open
`[start_date, end_date)` the original request specified.** Every other
report here — Income Statement's `date_from`/`date_to` in particular,
the closest existing analog (also a range, not a snapshot) — treats
both ends as inclusive. Introducing a second, differently-shaped date
convention for one report would be a worse outcome than the mismatch
with the request's own notation; a user picking "Aug 1" through "Aug
31" on this report should get the same days a user picking the same
two dates gets on Income Statement.

**Deferred, per the request's own Open Questions:** whether a brokerage
sweep/money-market account counts as cash is a per-account editorial
call, not a rule this feature tries to infer — `/accounts` gets a plain
toggle (`is_cashflow`, alongside the existing `is_postable`/`is_active`
ones) so a self-hoster can flip it themselves; nothing here guesses at
brokerage/retirement accounts either way beyond `db/seed.sql`'s own
starter chart leaving them off. The `category_id` rollup layer (phase
2, for trend/forecast views where accounts churn) is untouched — v1 is
account-level only, matching every other report in this app before any
of them grew a rollup dimension of their own.

**Addendum — equity-contra legs are a ledger adjustment, not an inflow
(supersedes the "opening-balance entries are not special-cased"
conclusion originally reached here).** The original reasoning above
considered two ways to treat the seed data's opening balance (`Dr
Checking, Cr Opening Balances Equity`) and rejected both: hardcoding
awareness of one particular account (fragile — wrong the moment a
self-hoster renames or restructures their equity accounts), or adding a
brand-new "this entry isn't real economic activity" flag the schema
doesn't have. It missed a third option, found later in review: `3100
Opening Balances` is already typed `account_type = 'equity'`, and that
column is exactly the "no special cases" mechanical signal the earlier
option was looking for — not a new flag, not an account-specific check,
just the same structural column Income Statement already treats as
authoritative for its own membership. In a *personal* ledger
specifically, no equity account represents a real transaction with an
external party the way a business's owner draws/contributions would —
every equity account in this app's own starter chart
([`docs/GUIDE.md`](docs/GUIDE.md)) is net-worth bookkeeping (opening
balances, retained earnings, unrealized gains) by construction, so
`account_type = 'equity'` cleanly separates "the ledger's own
continuity" from "something happened in the world this period" with no
per-account judgment call needed.

The reason this had gone unnoticed until a real seeded book was actually
loaded and viewed: on the demo/seed data, one opening-balance entry
($85,000) sits right at the start of ACTUAL's history, dwarfing every
real inflow/outflow for the same period by 4–5×, and — because the
report's *default* date range is month-to-date — it's not an edge case
a user has to go looking for with a wide date range; it's literally the
first thing every self-hoster sees the first time they open this report
after following the app's own documented setup flow. `net_change` stays
correct throughout (equity legs were never mis-summed, just
mis-*labeled*), so nothing about this was a tie-out failure — the
three-way check has no way to know "this number is real but
misleadingly grouped," only "does this number add up."

**Rejected: excluding equity-contra legs outright**, the same way a
pure cash-to-cash transfer is excluded. Unlike a transfer, the cash
genuinely left the ledger's "nowhere" and entered a real account — the
tie-out's `beginning + net_change == ending` identity needs that
counted *somewhere*, or the statement stops reconciling against the
balance sheet for any period that includes one. The chosen fix is
presentation, not deletion: `cash_flow_rows()` (`modules/reports/
service.py`) still sums every leg's own signed contribution into
`net_change` exactly as before — equity legs are only ever regrouped
into their own **Ledger adjustments** section (rendered between
Outflows and Net change in cash), never blended into Inflows/Outflows as if they
were income or spending, and never dropped from the total. The section
only renders when non-empty, since most periods — including every
period after the one where a self-hoster's books started — have no
equity-contra activity at all.

One further consequence, purely as a side effect of always computing a
beginning balance now (see the next addendum): **Beginning cash balance
and Ending cash balance render on every load**, not only inside the
tie-out failure banner where they were previously computed but never
shown. `_cash_flow_tie_out()` already calculated both for the
reconciliation check; they just weren't surfaced on a passing report,
so there was no way to sanity-check "net change from *what*" without
digging into a CSV export or the Balance Sheet separately.

**Addendum — a single income leg absorbs its own expense-typed
deductions ("reducible income"), while asset/liability legs never do.**
A second, distinct question surfaced independently of the equity fix
above: gross-to-net payroll (`Dr Cash 100, Dr Income Tax Expense 10, Cr
Wage Income 110`) is correctly *attributed* by the sign-flip rule this
decision already establishes — `Salary +110`, `Income Tax -10`, both
exactly right, nothing left to fix about the arithmetic. But two honest,
correct numbers can still be the wrong altitude for what a reader of
this specific report needs: withheld tax was never disposable cash the
account holder had and then spent — it left before the money was ever
theirs to control, mandated by law, with nothing received in exchange —
which is a materially different situation than a 401(k) contribution on
the very same paycheck (an *allocation* of cash the account holder
actually received, into an asset they still hold, just illiquid). Both
are "automatic" in the sense that neither is a discretionary purchase
decision, but only one of them represents gross income the reader never
actually realized as cash.

The mechanical signal that separates the two turns out to be the same
one the equity addendum above uses — `account_type` — applied to a
narrower, well-defined shape: **an entry with exactly one income-typed
non-cash leg and one or more expense-typed non-cash legs collapses into
a single row, under the income leg's own account, valued at their
signed sum** (exact by the same balanced-entry identity the rest of
this decision already relies on — nothing estimated). Asset and
liability legs on that same entry — a 401(k) contribution, a loan
payment, a credit card charge — are never folded in, regardless of what
else is on the entry; they itemize exactly as before. `_cash_flow_rows()`
implements this in Python, on top of `fn_cash_flow_lines`' unchanged
output — the SQL layer still returns one row per (entry, non-cash leg)
at full face value, since that's still the right shape for a BI tool
connecting directly to Postgres (decision 6's "the number should be
computable by SQL alone" is about the underlying figures, not about how
one particular report chooses to group them for display).

Two rejected alternatives, both raised and set aside during design:

- **Deleting the folded-away legs outright**, showing only the net
  figure with nothing else. Rejected for the same reason the "tempting
  fix" earlier in this decision was rejected for the store-credit
  counter-example: it destroys traceability, and — worse here — it
  would make the Cash Flow Statement's own "Salary" line disagree with
  Income Statement's, which pulls the same account's real ledger
  balance (the full gross figure) for the same transaction, with
  nothing on either report explaining why. The shipped version instead
  demotes the folded legs to a `netted_from` annotation on the row (a
  dim "net of Income Tax -10.00" sub-line, still linking through to the
  real entry) — nothing is deleted, only de-prioritized from a peer
  report line to supporting detail.
- **Netting whenever a cash-touching entry has more than one non-cash
  leg**, regardless of account type — the simplest possible rule, and
  wrong: it would swallow the 401(k) leg into the paycheck too, hiding
  exactly the kind of allocation a personal-finance user most wants
  visible. `account_type` is what makes the distinction principled
  instead of ad hoc — it's the same structural column every account
  already carries, not a new per-account opt-in the way `is_cashflow`
  is, so it requires no extra editorial effort from a self-hoster and
  works identically regardless of how they've named or organized their
  own chart of accounts.

**Two or more income legs on one entry are deliberately left
un-netted.** If a shared deduction rides alongside two income legs (a
combined salary-plus-bonus paycheck with one tax line covering both),
there is no principled way to decide which income leg the deduction
belongs to — any split would be invented, not derived, the same
objection this decision already raises against the earlier-rejected
proportional-weighting formula. Rather than guess, the entry backs off
to full itemization, exactly as if the netting rule didn't exist for
it — same posture as the multi-cash-leg flag: surface ambiguity, never
silently resolve it with a plausible-looking number.

This also does not reopen the hazard the "second, tempting fix" earlier
in this decision warned about (dropping the store-credit leg of `Dr
Shopping 100.00, Cr Store Credit 33.33, Cr Checking 66.67` would hide
that $100 was spent). That entry has no income leg at all, so the
netting rule never fires for it regardless of how `Store Credit` is
typed — Shopping and Store Credit itemize exactly as the sign-flip rule
already produces them. The reducible-income rule only ever *folds
toward* an unambiguous income leg; it has no mechanism that drops a leg
from the report outright, in this shape or any other.

### 21. `pct_of_base`'s two variance formulas: one consistent `base`/`compare_val` role everywhere, not "whichever argument order made a report's own default read right"

Income Statement, Variance, and Budget Grid all show a Variance and %
Variance column and share one toggle (`pct_of_base`, the "Flip variance
direction" checkbox) that swaps which of the two scenarios being
compared is measured *from* — the standard percent-change reading,
`(new - old) / old`. `_variance_amount()`/`_pct_variance()` are the one
shared implementation every call site uses.

Before this decision, every call site passed its own report's primary
figure and reference figure as `base`/`compare_val` in whichever order
made that report's *default* (unchecked) state divide by what felt like
the natural denominator for that report specifically. Income
Statement's and Budget Grid's calls put the primary figure first
(`scenario`/`actual`) and the reference second (`compare`/`budgeted`),
so the unchecked default divided by the reference — "actual came in 12%
under budget." Variance's own calls put the two in the *opposite*
order (`compare` first, `baseline` second) so that its unchecked
default divided by `baseline` instead — a deliberate choice at the
time: `baseline` is the one figure Variance always calls a report
"about" (you pick a baseline, then compare other things to it), so
having it always land in the denominator position regardless of which
report you were on read as the more useful invariant than argument-order
consistency between reports would have.

That asymmetry is gone. Every call site now passes `base` = that
report's own primary figure and `compare_val` = whatever it's measured
against, in the same positional order everywhere — Income Statement's
`scenario` then `compare`, Variance's `baseline` then `compare`, Budget
Grid's `actual` then `budgeted` — full stop, no per-report exception.
The default reading is now `(base - compare_val) / abs(compare_val)`
everywhere ("actual came in 12% *ahead* of budget" — note the sign is
also flipped from the old default's "12% under," a second, independent
change bundled into the same pass since both came from the same
concrete request); checked swaps to `(compare_val - base) /
abs(base)`. The XLSX export's own live formulas
(`_xlsx_variance_formulas`, `docs/ARCHITECTURE.md`'s XLSX export
section) mirror this exactly, cell-for-cell, rather than reimplementing
either convention independently — the same reasoning decision 19's own
"thin wrapper, not a parallel calculation" choice already established
for Split.

The `pct_of_base` query parameter itself keeps its name — it's a public,
bookmarkable query string on four routes plus their exports, and
renaming it would have meant a much larger, riskier diff for a name
that's an internal identifier most people who bookmark a report URL
never actually read. Only the checkbox's own visible label changed, to
"Flip variance direction" — the old "% variance of actual" label
happened to still be *technically* accurate under the new formula for
its checked state (checked still divides by whatever's playing `base`),
but the old wording was written to describe a report-specific
denominator choice that no longer differs report to report, so keeping
it risked implying a subtlety that isn't there anymore.

### 22. Find Duplicates matches on the full leg set, merges by deleting the losers, and resolves one group per click

Staging can end up holding two (or more) journal entries that are
really the same real-world transaction, proposed twice — a CSV import
whose date range overlapped an earlier one, or an active schedule that
also appears in an imported file for the same period. Find Duplicates
(`/staging/duplicates`) scans every pending entry at once, no selection
needed first, and groups them for review rather than guessing which
one to keep automatically.

**The matching rule is the full leg set as a set, not a pairwise or
partial check.** Two entries are duplicates only if they share the same
date and the same multiset of (account, amount) pairs across *all*
their lines — same count, same members. A 2-leg entry and a 3-leg entry
can never match each other regardless of what their first two legs look
like; a "duplicate" is specifically "the same transaction proposed
twice," not "a transaction that resembles another one." This is the
same identity-not-similarity instinct decision 20's cash-flow
attribution already leans on elsewhere in this schema — no fuzzy
scoring, no partial-match threshold to tune.

**A group's own label names the transaction, reusing the Dashboard's
existing flow-arrow convention** ("Credit Card → Groceries," credit
side first) rather than inventing a second way to describe a
transaction's direction — collapsing to "multiple" on either side for a
3+-leg group the same way the Dashboard's own recent-activity widget
already does, for the same reason: naming every account on a wide split
reads worse than admitting there are several.

**Merging deletes the losing entries outright; it does not reverse
them.** This is decision 15's own append-only exemption, not a new one:
every entry in a duplicate group is still sitting in Staging, still
`promoted_entry_id IS NULL`, so none of them were ever approved into
real books — there is nothing to reverse, only proposals to withdraw,
exactly the same reasoning Staging's own Reject action already relies
on. The surviving entry keeps its own row (and so its own id, and its
own `scheduled_entry_id`/`import_batch_id` provenance, untouched) rather
than a fresh entry being created to represent the merge; its
description/reference/payee/tags take whatever was chosen in the merge
step (already legal on a pending entry per decision 15), and each of
its own *lines* may get a new memo — legal specifically because of
decision 16's memo addendum, landing in the same release as this
feature and used directly here: a duplicate-derived memo edit is no
different in kind from a Journal click-to-edit one, just applied by a
merge form instead of a single input.

**Memo candidates come from the matching leg only, never a guess across
a different one.** When the survivor's own line has no memo yet, the
merge popup looks for the first non-blank memo on the *same*
(account, amount) leg among the other checked duplicates — the
identical reasoning the matching rule itself already establishes: same
account and amount is what makes two legs "the same line" across
entries, so borrowing a memo from anywhere else on another entry would
be attaching a note to a leg it was never actually written about.

**One group merges per click, not a batch across every qualifying
group at once.** If checking boxes across multiple groups would enable
Merge for more than one of them simultaneously, clicking it resolves
only the first (in document order) — same one-atomic-action-per-submit
shape decision 18's own Payee/Tag Merge already established, for the
same reason: "which description, which tags, which memos" is a real
decision with its own popup, and batching several such decisions behind
one click either forces one set of answers onto every group (wrong,
the whole reason a review page exists) or means building a queue of
sequential popups for a feature that doesn't need one. The merge
route's own flash-redirect already reloads `/staging/duplicates` and
recomputes groups fresh, so resolving the next group is just clicking
Merge again — including the case where merging the first group also
happens to leave zero groups behind, which lands back on `/staging`
with "No duplicate entries found" the same way an empty scan does.

**No client-side progress indicator on the FIND DUPLICATES link
itself**, despite the original request describing one — the detection
query runs over data already sized to fit comfortably in one page load
(everything currently pending in Staging), so it resolves before a
manufactured progress bar would have anything real to report. The
browser's own navigation-loading affordance already covers "something
is happening"; inventing a fake one on top would be decorating an
instant operation, not informing anyone about a slow one. Worth
revisiting only if Staging's pending count ever grows large enough for
the scan itself to be the slow part, which nothing about today's usage
patterns suggests.

### 23. Importing single-entry files is a per-import mapping, not a persistent rules table

Some export formats never had double entry in the first place — one
row per transaction, an Account column and a Category column, no debit/
credit of their own (ActualBudget's own CSV export is the concrete
example this was built against). `/import` already expects a file that
*is* double-entry shaped (`Entry #`/`Account code`/`Debit`/`Credit`
columns); this needed a second importer that builds the double entry
first, from a file that never had it.

**A "rule" is three mapping tables scoped to one file, not a saved,
named, reusable ruleset.** `/import/mapped` walks the wizard in three
steps, each its own mapping: which of *this file's own* columns (in
whatever the export actually calls them — "Merchant," "When," "Memo,"
anything) is the Money Account, the Entry Date, the Amount, and
optionally the Payee/Notes/Category; then, once those are known, which
real PostWarden account each distinct Account value and each distinct
Category value represents. Account values map to the "money" leg (the
checking account, the credit card); Category values map to the "other"
leg (an expense/income account, or a single chosen catch-all for
whatever the export left blank). None of this ever touches the
database — every step's choices round-trip as ordinary JSON fields
between screens, alongside the file's own content (base64), so there is
nothing to name, save, version, or clean up between "here's my file"
and "here's how to read it." This is the literal reading of the
feature's own ask: a screen to add rules for *this* import, not a
rules-library feature — and it means no new table, which a persistent
named-ruleset version would have needed (one for the ruleset, one for
its conditions/actions).

**The column-mapping step is what makes "any CSV shaped like this"
actually true, not just "any CSV ActualBudget happens to produce."**
The importer originally required the file's own header row to read
literally `Account,Date,Payee,Notes,Category,Amount` — true of
ActualBudget's export by construction, false of a bank's own CSV or
anything else with different column names, which needed a manual
header rename before this importer would even parse them. `POST
/import/mapped/columns` sniffs the uploaded file's real headers (plus a
few real sample rows, so a column can be matched by looking at its
data, not just guessing from a header like "Desc") and hands them to
the wizard's first screen; the seven target fields it offers
(`service.IMPORT_MAPPED_FIELDS` — Money Account/Entry Date/Amount
required, Payee/Entry Description/Line Memo/Category optional) are the
one place that list is defined, read by both the mapping-step picker
and the parse step's own validation. "Money Account"/"Category" are
deliberately not both just "Account" here, the one place in the wizard
where a plain reader could otherwise confuse which leg a mapping choice
is picking. Likewise Entry Description and Line Memo are separate
targets rather than one field silently feeding two different downstream
uses: the original ask mapped a Notes-shaped column to the entry
description, the shipped code instead derived the description from
Payee (falling back to Category, then a fixed placeholder) and used
Notes for the line memo — both are legitimate, so both are now visible,
named options rather than one hidden implicitly inside
`transform_mapped_rows`. Leaving Entry Description unmapped keeps that
same payee/category/fallback chain; mapping it overrides the chain
outright.

**The mapping table itself is oriented file-column -> target, one row
per column the file actually has, not target -> file-column.** The
original design here (and the feature's original ask) was one row
per *column found in the file*, each with a dropdown of PostWarden
targets defaulting to Ignore; what shipped in the first cut was the
inverse — one row per target field, each with a dropdown of the file's
columns — for three reasons that seemed reasonable at the time: required-
field validation reads at a glance in a short fixed-length table,
"Ignore" needs no explicit option since an unpicked column is just never
selected, and the table stays a constant six rows however wide the file
is. All three have real answers that flipping back doesn't give up: a
live "still needed: …" strip above the table is more legible than
scanning a fixed table for a blank anyway; an explicit "— ignore —"
default is *itself* the point, not overhead to avoid — the flipped
table forces a decision about every column, where the original one
silently dropped whatever a user never happened to pick, and on a wide
export (a 28-column bank CSV, say) there was no way to tell which two
thirds of it the importer had ignored. The one thing the flipped
orientation can express that the target-oriented one couldn't at all:
two different file columns both claiming the same target (two Date
columns, say) — the row-per-target shape structurally prevents that
from ever happening, at the cost of the column silently overwriting
whichever showed up first if you tried it the other way. That check now
lives client-side, in `ImportMappedPanel.tsx`, at the point where the
raw per-column choices still exist — by the time they're inverted into
the wire's target-keyed `column_map` (still target-key -> column
internally; only the picker's own orientation changed, not the request
shape), a second claim on one key has already silently overwritten the
first with no way to tell after the fact.

**Sign convention is fixed, not configurable per rule**: a negative
`Amount` debits the Category account and credits the Account (money
out increases an expense, decreases the money account); positive is
the mirror image. A `Flip Amount's sign` checkbox handles the export
whose convention runs the other way, rather than exposing sign logic
per mapping row — every row in one file follows the same convention, so
per-row control would be a knob nobody needs to turn twice.

**Deliberately not a conditional rule engine.** The feature's own
original example included a second rule shaped
differently from the first — "IF account is X AND Notes contains
'withdrawal' THEN debit Cash / credit Savings," an override that has
nothing to do with Category at all, for the transfers and cash
withdrawals a personal-finance export usually leaves uncategorized.
Building that would mean a real condition/action structure (match on
Account, Notes-contains, arbitrary boolean combinations) — a
meaningfully bigger feature than "map each distinct value to an
account" once actually scoped out, and the two don't obviously share
much implementation once you have both. `/import/mapped` instead folds
every blank-Category row into one bucket the user maps to a single
account of their choosing; a file whose blank-Category rows are *all*
one kind of transaction (all withdrawals, say) maps correctly by
picking that account. A file mixing several kinds under one blank
Category (a transfer next to an uncategorized refund, as in this
feature's own manual testing) doesn't — those rows land against
whichever single account got chosen for "no category," silently wrong
rather than flagged, and need a manual reclass in the Journal
afterward. Documented here rather than quietly shipped as if it covered
every case; a real conditional layer is the natural v2 if this gap
turns out to matter in practice, built as its own feature rather than
bolted onto the mapping model above.

**No validation beyond "is this a real, postable account" until the
transform step.** `/import/mapped/preview` never touches the database
except to list postable accounts for the picker — it doesn't check
dates, amounts, or balance anything, since at that point there's still
only single-entry rows, nothing to balance yet. Every actual check
(numeric `Amount`, ISO `Date`, a mapping chosen for every value a row
actually uses) happens once, in `_transform_mapped_rows()`, at the
point where a row is about to become a real two-line group — the exact
same "validate everything before touching the database, report bad
rows by number, never partially commit" shape `_parse_csv_import`
already established for the plain importer (decision 9's own
`import_batches` conventions), reused via one shared
`_stage_import_groups()` helper so both importers insert through
identical code.

**A "dialect" — delimiter, leading rows to skip, decimal/thousands
separator, date format — is sniffed once, up front, and edited in place
rather than becoming a fourth wizard step.** Nothing before this point
in the wizard could read a European bank
export at all (`;`-delimited, `1.234,56` amounts) or a file with a
title/timestamp line above the real header — both just failed outright,
with no control anywhere to fix them. `POST /import/mapped/columns`
sniffs a guess (`service.sniff_dialect`) alongside the columns it always
returned; the dialect panel that guess feeds sits *inside* the
column-mapping step, not a separate screen, because changing the
delimiter or how many rows to skip can change what the file's columns
even are — `POST /import/mapped/columns/reparse` re-reads the same
already-uploaded file (never a new upload) against whatever the user
just edited, and the mapping table below updates live from its response
(R2: always the file's real data, never a stale snapshot of the initial
guess). `decimal_separator`/`date_format` never change what the columns
are, only how `transform_mapped_rows` reads the Amount/Date cells later
— editing either doesn't clear an in-progress column mapping, unlike a
delimiter or leading-rows edit, which can.

Sniffing the delimiter turned out to need its own fallback chain, not
just a single `csv.Sniffer()` call: a blank line anywhere in the sample
is enough on its own to make `Sniffer` raise `Could not determine
delimiter` rather than fall back to a plausible guess, which combined
badly with a junk line above the header (both are exactly the shapes a
real export tends to have together, a title line followed by a blank
line before the real table starts). `_sniff_delimiter` strips blank
lines and retries from progressively later starting points until one
succeeds, falling back to comma only once every starting point has
failed — caught by browser-testing this exact combination against a
real file, not by the unit tests alone, which is why that combination is
now also a regression test (`test_sniff_dialect_detects_the_delimiter_
past_a_junk_line_and_a_blank_line`).

Deliberately excludes encoding. `decode_upload`'s `utf-8-sig` already
strips a BOM'd Excel export's one real gotcha; true multi-encoding
detection (Latin-1/Windows-1252 exports) waits for R7's second file
format to justify the abstraction, rather than being guessed at now with
no second format to test it against. Also out of scope for this phase:
dot-separated dates (`01.03.2026`, common in German exports) — only
slash-separated `MM/DD/YYYY`/`DD/MM/YYYY` are recognized; a file using
dots falls back to the `iso` guess and reports a per-row date error
until the user picks a different `date_format`, at which point it still
won't parse (`_DATE_FORMAT_STRPTIME` has no dot-separated entry). Known,
not fixed — the dialect work's four explicit test cases (semicolon/
comma-decimal, `DD/MM/YYYY`, a BOM'd export, junk rows above the header)
are all slash- or ISO-dated; a dot-date format is a small follow-up, not
a blocker, whenever a real file surfaces the gap.

**A validation report replaced the flat error banner, for the mapped
importer only** (the wizard's validation step — `ROADMAP.md`'s import
track R3, now shipped).
`transform_mapped_rows`' `errors` used to be a `list[str]`, each entry a
pre-formatted `"Row N: ..."` message, joined and truncated at
`IMPORT_MAX_ERRORS_SHOWN` wherever it surfaced. It's now a structured
`list[{row_no, raw, message}]` — `raw` is the row exactly as `parse_
mapped_file` produced it, so a real table can show what was actually in
the file (date, account, category, amount, payee) next to why it failed,
not just a joined string; truncation for display moved to the frontend,
since the value itself is no longer pre-formatted for one particular
rendering. A new pure endpoint, `POST /import/mapped/validate`, runs the
same transform `POST /import/mapped` commits with — against the same
account/category maps — but never touches the database; the review
step's own Confirm calls it first, and only shows the new
validation-report screen when it comes back with any row errors at all
(R1: a clean file's `errors` is empty and staging happens immediately,
exactly as this step always behaved, no extra screen for the common
case). `import_mapped` gained `skip_bad_rows: bool = False` to match: a
row error now blocks the whole commit unless the caller explicitly opts
in, rather than the old implicit "stage what worked, report the rest" —
an API caller that skips `/mapped/validate` and posts straight to
`/mapped` with row errors present gets exactly that block, the same
protection a human clicking through the wizard gets from actually seeing
the report first.

Scoped to the mapped importer specifically, not `parse_csv_import` (the
plain importer). Its own errors mix per-row (`"missing Account code"`)
and per-entry, multi-row (`"doesn't balance"`, spanning every line of one
`Entry #` group) failures in ways that don't reduce to one `{row_no, raw,
message}` per row as cleanly as the mapped importer's always-one-row-one-
entry shape does; it's also a smaller, more mechanically fixed file
format to begin with (real double-entry CSVs with required exact column
names, not arbitrary bank exports). Left as a plausible follow-up, not
attempted here — `parse_csv_import`'s errors stay a flat `list[str]`,
`ImportPlainPanel.tsx` stays a single flash banner.

**Addendum (decision 24):** the "two importers" framing above is now
historical. The wizard merge collapsed `/import` and
`/import/mapped` into the one pipeline decision 24 describes — every
reason given here for a per-import mapping (not a persistent ruleset),
sniffed/editable dialect, and a structured validation report still
holds, now for every file shape rather than the mapped importer alone.
`parse_csv_import`, `ImportPlainPanel.tsx`, and the flat-`list[str]`
error shape this decision described as the plain importer's own
carve-out are gone; see decision 24 for what replaced them.

**Addendum (post-Phase-4 fix):** "Money Account"/"Category" — described
just above as deliberate — turned out to be the wrong deliberate choice.
David flagged, after using the shipped wizard, that both read as if they
named real PostWarden data fields when neither does; PostWarden's schema
has no `category` concept anywhere. `target_fields_for_shape`'s
`"one"`-shape labels are now "Account"/"Other Account" — still two
distinguishable account pickers (the reason given above for not making
both bare "Account" still holds), just without borrowing ActualBudget's
own vocabulary to do it.

### 24. Shape is a wizard property, not a choice of importer

Decision 23 gave single-entry exports their own importer because
`/import` only understood one fixed layout: rows grouped by `Entry #`,
a Debit/Credit column pair, `Account code` cells already holding real
codes. That layout was never actually special — it was one point in a
small space of choices (one row per entry or several grouped by a key
column; a signed amount or a Debit/Credit pair; a lookup column holding
a real code already or a label that needs mapping) that the plain
importer happened to hardcode and the mapped importer happened to
leave unconfigurable the other way. The wizard merge made
every one of those choices an explicit wizard setting instead, and
`parse_csv_import`/`parse_mapped_file` — two parsers that had quietly
converged on the same shared `_stage_import_groups()` landing step
anyway — collapsed into one pipeline that reads them.

**`shape` is `{rows_per_entry: "one"|"grouped", group_key_column: str|
None, amount_style: "signed"|"debit_credit"}`.** `sniff_shape` guesses
it from the file's own columns and sample rows the same way `sniff_
dialect` already guessed delimiter/decimal format (decision 23's own
account) — a case-insensitive Debit/Credit pair and a repeated-value
column that looks like an id/entry/transaction key both nudge the
guess toward `"grouped"`/`"debit_credit"`; anything ambiguous falls
back to `"one"`/`"signed"`, the mapped importer's original and simpler
default (R1: never block on a wrong guess, since every field is
still editable). `target_fields_for_shape(shape)` replaces the fixed
`IMPORT_MAPPED_FIELDS` list decision 23 described — the mapping step's
own target-field list is now a function of `shape`, not a constant: a
`"grouped"` shape adds a required `group_key` target with no lookup
capability of its own, and `amount_style` swaps a single `amount`
target for a `debit`/`credit` pair or back.

**`column_kinds` (per lookup-capable column, `"code"` or `"label"`)
generalizes what decision 23 only ever needed implicitly.** The plain
importer's `Account code` column always held a real code; the mapped
importer's `Account`/`Category` columns always held labels needing
`account_map`/`category_map` — the merge makes that a per-column choice
rather than an assumption baked into which importer you happened to
be using, and `value_maps: dict[key, dict[str,str]]` generalizes
`account_map`/`category_map` into one map per `"label"`-kind column
(in practice still 0, 1, or 2 maps, since only `account`/`category`
are ever lookup-capable — this is *N grouped rows, one leg per row*,
decision 23's own R9 boundary, not a single row expressing an
arbitrary multi-way split, which stays future work regardless).
`column_kinds`' default (`"label"` unless the shape is exactly
grouped+debit_credit+account, which defaults to `"code"`) is a
structural heuristic over `shape`/`amount_style` alone, deliberately
not a live check against real account codes — keeps `parse_file`/
`transform_rows` genuinely `Connection`-free (R12), the same purity
`parse_mapped_file`/`transform_mapped_rows` always had.

**`known_codes: set[str] | None` restores per-row "unknown account
code" diagnostics without breaking that purity.** A `"code"`-kind
column's value is trusted verbatim by `transform_rows` unless the
caller also passes in a bulk-resolved `set` of real codes (`known_
account_codes`, one query, run once by whichever router handler
needs it) — `None` means every pure unit test, and the caller's
grouped-row diagnostic degrades gracefully to `stage_import_groups`'s
own blanket "Unknown account code" check instead of failing per-row.
This is the one place the merge added something decision 23's original
design didn't need: `parse_mapped_file` never had a code-kind column
to resolve at all.

**The error shape decision 23 scoped to the mapped importer alone
(`{row_no, raw, message}`, vs. the plain importer's flat strings) is
now the only shape, for every file.** A grouped shape's balance
failure still reports exactly one error per group, keyed to the
group's first row — `parse_csv_import`'s own historical granularity,
preserved rather than exploded into one error per row in the group.
`parse_file` keeps flat strings for structural errors only (a required
column missing, an unknown mapped column, an empty file) — the same
split `parse_mapped_file` already had.

**`skip_bad_rows` now blocks by default for every shape, not just the
mapped importer's** — a deliberate behavior change from `parse_csv_
import`'s old "stage what worked, report the rest" default for a
grouped/Debit-Credit file, confirmed with David before implementation
started. Every shape now needs the same explicit "stage the rest, skip
these" opt-in a bad row used to skip automatically for the plain
importer alone. (For the one sub-phase between the compatibility shim
landing and `POST /import`'s removal, a plain-format CSV with any bad
row therefore failed outright rather than partially staging — a
short-lived, documented regression rather than a silent one, gone the
moment the route itself was deleted.)

**The merge happened in two steps, not one big-bang cutover**: first
every new primitive (`shape`, `parse_file`, `transform_rows`, `preview_
file`/`validate_file`/`import_file`) shipped alongside the two old
implementations, wired into `/import/mapped/*` only; then `POST
/import` became a thin shim over the same pipeline
(`IMPORT_PLAIN_SHAPE`/`IMPORT_PLAIN_COLUMN_MAP`/`IMPORT_PLAIN_COLUMN_
KINDS` fixing every wizard choice a real user of the mapped importer
would otherwise make by hand) before `parse_csv_import` was deleted;
only once `ImportMappedPanel.tsx`'s own Shape step could reproduce the
plain importer's grouped/Debit-Credit/direct-code format as a default
did `ImportPlainPanel.tsx` and `POST /import` disappear outright. One
subtlety the shim surfaced that the two-parser design never had to
face: `parse_file`'s structural check treats every `column_map` entry,
required or not, as a promise the file has to keep — unlike `parse_
csv_import`'s old bare `row.get("Reference")`, which silently read
`None` from a column that simply wasn't there — so the shim has to
sniff the file's real columns first and only map an optional field
(`Reference`/`Payee`/`Memo`) when it's actually present, or a
perfectly valid file missing those three columns would fail outright.

### 25. A custom report is a closed enum allowlist over the reporting layer, never a query language

The Report Builder (`/app/custom-report`, `GET /reports/custom`) lets a
user compose a report — one metric, one breakdown dimension, typed
filters, a chart type — without a developer hand-building a page for
every shape. The obvious reference point, ActualBudget's custom
reports, runs its query engine *in the browser against a local SQLite
replica*; PostWarden is a server-side Postgres app reached over HTTP by
a thin SPA, so the thing that turns a report config into SQL runs on
the server, with real credentials, against the real ledger. That trust
boundary — not a lesser ambition — is the design driver: **a report
config sent from the browser is a closed enum of pre-vetted choices,
never an arbitrary filter expression or field name.**

Concretely:

- **`Metric` and `Dimension` are Python `Enum`s in the route signature
  itself** (`modules/custom_reports/enums.py`), so FastAPI 422s an
  out-of-allowlist value before any code runs, and each member maps in
  Python to exactly one pre-written query fragment
  (`repository._METRICS`/`_DIMENSIONS`) — never string-interpolated
  into SQL. Filters are typed the same way (a date range, ids validated
  against real `accounts`/`tags`/`scenarios`/`payees` rows, the
  `account_type` Postgres enum mirrored as a typed filter) and bound as
  parameters. Adding a metric or dimension means adding an enum member
  *and* its fragment — and if a wanted report can't be expressed as an
  enum addition, that's a signal to open a new numbered decision here
  about why, not to quietly grow this into a general query language.
- **The allowlist ships at compile time, not runtime.** The generated
  typed client (`frontend/src/api/schema.ts`) exposes the enums as
  TypeScript union types, so the frontend's dropdowns are checked by
  `tsc` against the backend's own allowlist — a member added
  backend-side without frontend handling is a compile error. No runtime
  "schema" endpoint exists, and none should.
- **The run endpoint is a GET with the whole config in the query
  string**, like every other report: that's what makes any composed
  report bookmarkable and shareable with zero save machinery, and it's
  the bridge to saved reports (a saved report is a named, validated
  query string — `ROADMAP.md` S5; validation happens on every run, not
  just at save, so replaying a stored config is safe by construction).
- **It queries the reporting layer that already existed for BI tools**
  (decisions 6 and 14): `v_fact_lines`, `v_monthly_activity`,
  `fn_rollup_balance`. The hard parts — hierarchy rollup, the
  debit/credit sign convention, tag denormalization — were already
  solved and already tested for a different consumer; the whole feature
  is a thin allowlisted access layer in front of them, which is why it
  shipped with no schema change at all.
- **Its own vertical slice** (`modules/custom_reports/`), not part of
  `modules/reports/` — the deletable-on-its-own test: it has a
  different shape (it grows write routes and `schemas.py` with saved
  reports; `modules/reports/` deliberately has neither), and the two
  merely share a URL neighborhood.

Deliberately out of scope, permanently: arbitrary boolean filter
trees (Actual's own UI is dropdown-and-chip driven too — matching that
UX never required a generic engine), ad hoc calculated fields, and any
client-side query engine or ledger replica in the browser — the
product's reason for being is Postgres as the single live source of
truth. Frontend rendering notes (Recharts as the first real UI
dependency, and the lazy-route pattern it forced) live in
`docs/ARCHITECTURE.md`, not here — rendering choices aren't schema
design.

### 26. The report-table tree is TanStack Table's row model, not a hand-rolled ancestor walk

`ROADMAP.md` S1's first slice: Trial Balance and Balance Sheet's
account trees render through a real `useReactTable` instance
(`@tanstack/react-table@8`, one per type-section) instead of
`useCollapsibleTree`'s own manual `parent_id` ancestor walk. Purely a
rendering-mechanics swap — `table.ledger.report-table`'s markup and
every CSS selector that keys off it (`.acct-name.depth-N`,
`.tree-toggle`, `tr.collapsed`, `tr[data-has-children="1"]`) are
untouched, so this is a decision about *how* a report page computes
"which rows are visible right now," not about how the tree looks.

- **8, not 9.** `@tanstack/react-table@9` was current on npm at the
  time and has a genuinely different, store/selector-based API
  (`useTable`/`createTableHook` in place of `useReactTable`) — a very
  recent major version, not what "adopt TanStack Table (headless)" was
  scoped against. Pinned to the mature v8 line (`useReactTable`,
  `getCoreRowModel`, `getExpandedRowModel`) instead of the newest major
  release, deliberately: this is meant to be a stable foundation
  several more reports build on (S6, S7), not a place to absorb a
  paradigm change mid-migration.
- **Headless, not styled.** The constraint was never losing Trial
  Balance/Balance Sheet's own look — a styled grid (AG Grid, MUI
  DataGrid) would mean re-approximating it; TanStack Table only
  computes row/column models and leaves every `<td>` to be hand-
  rendered exactly as before.
- **One `useReactTable` instance per type-section** (Assets,
  Liabilities, ... — `GroupRows`/`SectionRows` in
  `TrialBalancePage.tsx`/`BalanceSheetPage.tsx`), not one spanning the
  whole report. Each section is already its own self-contained tree —
  no real account's `parent_id` ever crosses a type boundary — so
  nothing is lost by not unifying them, and a per-section `data` array
  (built from that section's own flat row list via a new
  `buildRowTree`, `widgets/useExpandedTree.ts`) stays simple.
- **One shared `expanded` record across every section on the page**,
  from one `useExpandedTree(storageKey, allRows)` call at the page
  level — TanStack tolerates a record entry for a row id its own table
  instance never sees, so sharing one controlled `expanded` state
  object across several `useReactTable` calls is safe, and it's what
  keeps the collapse state one flat concept per page instead of one
  per section.
- **Same on-disk shape, new in-memory one.** `useExpandedTree` reads
  and writes the exact `localStorage` key `useCollapsibleTree` already
  used, in the same format (an array of collapsed numeric ids) —
  nobody's saved collapse state resets by moving a report onto this
  hook. Internally, though, TanStack's `ExpandedState` inverts this
  app's own default: a row *missing* from the record reads as
  collapsed, where this app's own default has always been expanded
  unless the user explicitly collapsed it. `useExpandedTree` bridges
  this by writing an explicit `true`/`false` for every row with a
  known id, every render, rather than only the collapsed ones.
- **The one real bug this surfaced**: `row.toggleExpanded()`
  (table-core's own `RowExpanding` feature) collapses a row by
  *deleting* its key from the record it hands to `onExpandedChange`,
  not by setting it to `false` — it relies on its own
  `row.getIsExpanded()` treating a missing key as falsy. A first pass
  at `onExpandedChange` checked for the literal `=== false` and missed
  the deleted-key case entirely, so a click silently did nothing.
  Worth recording because it's exactly the kind of thing a future
  report's own expansion wiring would re-discover the hard way:
  build the next `expanded` record with `!record[id]` (falsy — missing
  or `false`), never `record[id] === false`.
- **`useCollapsibleTree` itself stays**, unchanged in behavior, for
  the five report pages not yet ported (Variance, Cash Flow, Ledger,
  Income Statement, Budget) — `ROADMAP.md` S6 moves each of those in
  turn. It gained one export (`loadCollapsed`) so `useExpandedTree`
  reads the same on-disk format via the same function rather than a
  second copy of the same six lines.

## Extension roadmap

Shipped since this list was first written: recurring/scheduled entries
(decision 9), reusable entry templates, and the income-statement-only
Budget grid (decision 3) — struck through below, left in place as a
record of what was originally proposed and how it actually landed.

- **Entity dimension** — add `entities` and `entity_id` on entries, and the
  same fact table consolidates multiple sets of books (elimination entries
  become just another scenario or a dedicated elimination entity, exactly
  as in CPM practice).
- **Multi-currency** — deliberately *not* scaffolded on `accounts` anymore.
  A `currency` column lived there for a while, unused end to end (no
  route ever set it past its own `'MXN'` default, no view consumer, no
  UI), and was dropped once that became clear (see git log around
  `accounts.currency`). GnuCash's model
  (an account is denominated in one currency; a cross-currency
  transaction's split carries its own `value_num`/`value_denom` pair
  against that) was the implicit template a per-account column was
  scaffolding toward, and it's the wrong shape for this app specifically:
  a checking account is a single real-world account regardless of what
  currency a given purchase against it happened to post in, so "what
  currency is *this account*" isn't actually the question multi-currency
  support needs answered — "what currency was *this transaction*"
  (or *this leg*, for a split that mixes them) is. If this ever gets
  built, `currency` belongs on `journal_entries` (or `journal_lines`,
  if two legs of the same entry can genuinely disagree), not `accounts`
  — plus a `prices` table (GnuCash's one good idea worth importing
  regardless) to translate in the reporting views.
- **Periods & closing** — a fiscal calendar table, closing entries
  generated per period, `is_locked` graduating from scenario-level to
  period-level. Partly pre-empted by decision 10 (the simulated close is
  a query, not a posting) — a real periods table would still be worth it
  for multi-period locking, just not for the close itself.
- ~~**Recurring entries** — templates + a scheduler posting real
  entries.~~ Shipped as `scheduled_entries` (decision 9) — with an
  approval layover through STAGING that wasn't part of the original
  proposal, added because posting straight to the target on the due
  date turned out to be the wrong default for a personal ledger.
- ~~**Import** — CSV/CAMT bank import posting suggested entries to a
  staging scenario for review before promotion to ACTUAL.~~ Shipped,
  landing in the STAGING scenario itself exactly as this predicted
  rather than a second approval mechanism. Originally two importers —
  `/import` for files that already carried real debits and credits,
  `/import/mapped` (decision 23) for single-entry exports that
  didn't — merged into the one `/import/mapped/*` wizard (decision 24):
  "grouped vs. one row" and "Debit/Credit
  vs. signed amount" are wizard settings now, not a choice of which
  importer to use, and `POST /import` itself is gone. Every shape still
  lands through the one shared `stage_import_groups()` insert path.
  CAMT specifically was never built — every real request for this has
  been CSV-shaped exports (bank statements, ActualBudget) rather than
  CAMT XML.
