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

### 7. Thin application, no ORM

`db/schema.sql` is the single source of truth; the FastAPI layer is plain
SQL through psycopg3. Every query in the app can be pasted into psql.
Server-rendered Jinja2 + ~100 lines of vanilla JS; no build step, no SPA.
The journal entry screen is keyboard-first — account, debit *or* credit,
Tab, next line appears — with a live balance bar; the Post button unlocks
only when the entry balances (client courtesy; the database re-checks at
commit regardless).

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
into two synthetic "Current/Prior Year Earnings (Unclosed)" lines under
Equity — as if a monthly close had actually run. It hasn't: this is
computed at request time from `fn_account_balances` called with two
different date windows and combined in Python
(`_trial_balance_rows()`), and `raw=1` turns it off to show the true
unmodified cumulative balances instead. No closing entry is ever posted,
consistent with "if a number matters, it should be computable by SQL
alone" (decision 6) — closing the books for real would mean a second
write path outside the one the balance trigger governs, which is exactly
what decision 2 exists to prevent.

### 11. Hierarchical rollups are built in the app, not SQL, and drill through uniformly

Trial Balance, Balance Sheet, and the Budget grid all show a summary
account's *rolled-up* subtotal (everything under it), not just its own
direct postings, with collapse/expand. `v_dim_account`'s recursive CTE
already gives every account its `path`/`depth` for free, but the rollup
itself (`_build_account_tree()` in `app/main.py`) is plain Python over
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
mechanics (the `data-id`/`data-parent`/`data-has-children` markup,
`report-tree.js`, the `entry_link` macro convention).

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

What actually shipped: `db/migrations/NNN_description.sql`, forward-only
(matching decision 4's own append-only ethos — a bad migration gets
fixed by a new one, never edited or rolled back), applied by
`app/migrate.py` once at every app startup, tracked by a one-row
`schema_version` table. `schema.sql` stays exactly what it's always
been — the full current state for a fresh install — with the discipline
that every migration also gets folded into it by hand, `schema_version`'s
seed bumped to match, so a new clone never replays migration history to
arrive at the same place.

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
quietly editing history it was never meant to touch. Payees keep both,
each doing the one thing its name promises. Tags only ever needed
Delete — nothing about "pending, not yet realized" applies to a
free-form label the way it does to a vendor you might pay again, and
decision 16 already means a tag with zero remaining uses isn't
cluttering anything; there's no equivalent "hide from future pickers"
need for Delete to sit alongside.

**Merge** is the other new piece, on both pages: fold two or more
selected rows into one. The alternative considered — auto-picking the
survivor's name (e.g. whichever has the most entries, or the
alphabetically-first) — was rejected because a merge is usually
prompted by realizing two names are the *same real thing under
different spellings* ("Trader Joe's" vs "Trader Joes"), and neither
existing spelling is necessarily the one worth keeping; the UI (see
`entity-manage.js` in `docs/ARCHITECTURE.md`) instead prompts for the
final name outright, pre-filled with the first selected row's name as
a sensible default but freely editable, covering "merge and clean up
the name" in one step instead of two. The surviving *row* (as opposed
to name) is arbitrarily the first one selected — its id is what every
foreign key gets repointed to — since which physical row survives is
invisible to the user the moment its name is set explicitly regardless;
only the merged-away rows' ids need to disappear, and any of the
selected ids would have worked equally well as the keeper.

## Extension roadmap

Shipped since this list was first written: recurring/scheduled entries
(decision 9), reusable entry templates, and the income-statement-only
Budget grid (decision 3) — struck through below, left in place as a
record of what was originally proposed and how it actually landed.

- **Entity dimension** — add `entities` and `entity_id` on entries, and the
  same fact table consolidates multiple sets of books (elimination entries
  become just another scenario or a dedicated elimination entity, exactly
  as in CPM practice).
- **Multi-currency** — accounts already carry `currency`; add a `prices`
  table (GnuCash's one good idea worth importing) and translate in views.
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
- **Import** — CSV/CAMT bank import posting suggested entries to a staging
  scenario for review before promotion to ACTUAL. The staging-and-approve
  mechanism this describes now already exists (decision 9) for a
  different producer (schedules, not an importer) — a CSV importer could
  likely reuse `materialize_due_schedules()`'s pattern (or the STAGING
  scenario itself) directly rather than inventing a second approval flow.
