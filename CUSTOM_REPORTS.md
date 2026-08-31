# Custom reports — design sketch (v1 shipped)

**Status: v1 shipped 2026-08-31**, as the Report Builder
(`/app/custom-report`, `frontend/src/reports/CustomReportPage.tsx`,
`src/postwarden/modules/custom_reports/`). Everything under "Phasing"
below marked v1 is built, tested, and documented in
`docs/ARCHITECTURE.md`'s archetype table and
`UI_CONSISTENCY_AUDIT.md` §2g. This document now describes what's live
plus what v2/v3 would still add — it's no longer a pre-build sketch, so
read the enum/filter/phasing sections below as "what v1 actually does,"
not "what's proposed." It's still internal planning like `BACKLOG.md`/
`UI_CONSISTENCY_AUDIT.md` — not in `mkdocs.yml`'s nav, not published to
`docs.postwarden.org`.

**Revised 2026-08-31**, after the React rebuild finished, to replace
the sketch's stale infrastructure assumptions (a runtime schema
endpoint, a POST run endpoint, a presumed-existing charting library and
subtotals table component) with what the rebuilt app actually provides.
The security architecture, enums, filters, and phasing were unchanged
from the original sketch, and v1 was built to this revision the same
day.

Origin: a conversation about whether an
[ActualBudget](https://actualbudget.org)-style "build your own report"
feature, previously judged too hard, is more reachable now that the
frontend is a React SPA (rebuild since completed — see
`docs/ARCHITECTURE.md` for the result). Relevant existing BACKLOG.md
items this refines: "Add graphs to reports/create new reports" and
"Connection with Power BI and external reporting tools" — this document
supersedes those bullets for the in-app version specifically; the
Power BI angle stays a separate, already-shipped path (`postwarden_bi`
role, see `docs/SCHEMA.md`'s Reporting layer section).

## Goal

Let a user compose a report — pick a metric, a way to break it down, a
date range and a few filters, a chart type — without a developer having
to hand-build a new page for every shape someone asks for. Cover the
common real requests already sitting in `BACKLOG.md` (spend by category
over time, income vs. expense trend, waterfall/pie breakdowns, balance
by account group) as *configurations* of one component, not as five more
bespoke report pages.

## Non-goals (and why)

Read the full reasoning in conversation history if this file gets
revisited without it, but the short version:

- **Not a generic query language exposed to the client.** PostWarden is
  a server-side Postgres app reached over HTTP by a thin SPA — unlike
  ActualBudget's local-first SQLite-in-the-browser model, the thing that
  would construct SQL from client input runs on the server, with real
  DB credentials, against the real ledger. A report "config" sent from
  the browser must be a **closed enum of pre-vetted choices**, never an
  arbitrary filter expression or field name — that's the actual
  difference from Actual's `loot-core`, not a lesser ambition, a
  different trust boundary.
- **Not arbitrary boolean filter trees.** Actual's own custom-report UI
  (see the screenshot discussed in conversation) is itself dropdown- and
  checkbox-driven, not a raw expression builder — Mode, Split, Type are
  all closed choices; filters are added one chip at a time. Matching
  *that* UX doesn't require a generic engine underneath it.
- **Not ad hoc calculated fields.** A user cannot define a new derived
  column live. New metrics/dimensions are added by a developer (one enum
  case + one query template), not composed at runtime.
- **Not a client-side query engine / local data replica.** Would require
  syncing a queryable copy of the ledger into the browser (e.g. a WASM
  SQLite mirror) — a materially bigger, unrelated undertaking, and
  orthogonal to where Postgres physically sits. PostWarden's reason for
  being is the DB-enforced double-entry integrity (`SPEC.md`); that only
  means anything with Postgres as the single source of truth queried
  live, not a replica.

## What already exists to build on

This is the part that changes the sizing estimate: PostWarden already
has a reporting layer built for BI-tool consumption
(`docs/SCHEMA.md`'s "Reporting layer" section, `SPEC.md` decision 14),
and it is exactly the layer a custom-report feature would sit on top of
— the hard parts (hierarchy rollup, debit/credit sign convention, tag
denormalization) are already solved and already covered by the existing
test suite:

- **`v_dim_account`** — every account with `path`/`parent_path`/`depth`
  (the recursive hierarchy walk, already done) and derived `normal_side`
  (debit- vs credit-normal, already correct per account type).
- **`v_fact_lines`** — one row per journal line, already denormalized:
  `entry_date`, `month`, `scenario_code`, `account_id`/`code`/`name`/
  `account_type`, signed `amount` plus presentation `debit`/`credit`,
  `payee`, `tags` (as an array). This is the star-schema fact table —
  a custom report's "give me rows matching these filters" is a `SELECT`
  against this view (or `v_monthly_activity` when the grouping is
  already account × month × scenario).
- **`v_monthly_activity`** — `v_fact_lines` pre-aggregated to account ×
  month × scenario — the direct source for a "metric over time, grouped
  by account" chart with no per-request aggregation needed.
- **`fn_rollup_balance(scenario, depth, as_of)`** — balances rolled up
  to a common `account_levels` depth. The "group by account at level N"
  dimension is this function, not new SQL.
- **`fn_cash_flow_lines`** — if a cash-flow-shaped custom report is ever
  wanted, the attribution logic (SPEC.md decision 20) already exists.

Consequence for scope: this feature is mostly a **thin, allowlisted
access layer** in front of views/functions that already exist and are
already trusted, plus a config schema, an endpoint, and a React
component. It is not "build a query engine" — that part shipped already,
for a different consumer (Power BI/Excel via the `postwarden_bi` role).

## Architecture

The original sketch predated the rebuild's generated typed API client
(`frontend/src/api/schema.ts`, via `openapi-typescript` — see
`docs/ARCHITECTURE.md`'s "typed API client" section) and imagined a
runtime `GET /api/reports/schema` endpoint feeding the config panel's
dropdowns, plus a `POST /api/reports/run`. Both are superseded:

- **The enum allowlist ships at compile time, not runtime.** `metric`
  and `dimension` are Python `Enum`s in the route signature, so the
  generated client exposes them as TypeScript union types — the
  frontend's dropdown list is checked by `tsc` against the backend's
  own allowlist, and an enum member added backend-side without frontend
  handling is a compile error, not a runtime surprise. No schema
  endpoint exists. (Display labels/descriptions live in a small
  frontend map keyed by the generated union type, so an unhandled
  member is likewise a compile error.)
- **Value lists need no new endpoint either** — the config panel's
  account/tag/scenario/payee/level pickers use the existing reference
  hooks (`api/useAccounts.ts`, `useTags.ts`, `useScenarios.ts`,
  `usePayees.ts`, `useAccountLevels.ts`).
- **The run endpoint is a `GET`, not a `POST`.** Every existing report
  is a read-only GET with the whole view state in query params — that's
  what makes reports bookmarkable/shareable and is the archetype
  convention (`UI_CONSISTENCY_AUDIT.md`). Same here: the entire config
  (metric, dimension, typed filters, repeated params for the
  include/exclude value list) lives in the URL. This also makes v2's
  saved reports nearly trivial — a saved report is essentially a named,
  validated query string. POST only enters in v2, for `saved_reports`
  CRUD. Note the `/api/*` prefix is not available for any of this —
  that namespace belongs to `analytics/` (the BI mirror, a shipped
  external contract); module routes are unprefixed, per
  `docs/ARCHITECTURE.md`.

```
Browser (React)
  1. config panel renders from compile-time enum types + the existing
     reference-data hooks — nothing here is free text
  2. user picks metric + dimension + filters + chart type
  3. GET /reports/custom?metric=...&dimension=...&date_from=...&...
     → FastAPI rejects out-of-enum values at the signature (422),
       service validates filter ids against real rows,
       dispatches (metric, dimension) to one pre-written query
       against v_fact_lines / v_monthly_activity / fn_rollup_balance,
       returns { rows: [...], meta: {...} }
  4. chart mode renders rows as bar/line/area/pie; table mode renders
     the same rows flat with a total row
  5. .csv/.xlsx sibling routes resolve the identical service result
     (same pattern as every report in modules/reports/router.py)
  6. v2: POST /reports/custom/saved etc. (saves the config as a named
     report)
```

The validation step in (3) is the entire security-relevant surface:
`metric` and `dimension` are enum members mapped in Python to a fixed
query builder function each — never string-interpolated into SQL.
Filters are typed (a date range, an account id validated against
`accounts`, a tag id validated against `tags`, a scenario id validated
against `scenarios`) and bound as query parameters, same as every other
route in the app already does.

### Where the code goes

- **Backend: a new vertical slice, `src/postwarden/modules/
  custom_reports/`** — not folded into `modules/reports/`, per the
  "deletable on its own" test (`docs/ARCHITECTURE.md`): this module has
  a different shape (it will grow `schemas.py` and write routes in v2;
  `modules/reports/` deliberately has neither). Standard slice layout:
  `router.py` (the GET + export siblings), `service.py` (filter-id
  validation, `(metric, dimension)` dispatch), `repository.py` (the
  pre-written `text()` queries — same style as `modules/reports/
  repository.py`, whose docstring is the reference for reading the
  reporting-layer views directly). Export siblings call the shared
  `src/postwarden/export/` writers.
- **Tests ship with the module**: `apitests/modules/custom_reports/`
  in the same commit, including tests that out-of-enum input 422s and
  that unknown filter ids are rejected.
- **Frontend: one new page under `frontend/src/reports/`** (Report
  Builder), plus its route in `App.tsx` and `shell/nav.ts`. It's a
  sixth archetype ("composable report") — register it in
  `UI_CONSISTENCY_AUDIT.md` §1 and `docs/ARCHITECTURE.md`'s archetype
  table when it ships.

## Metric enum (v1, shipped)

| Enum value | Meaning | Source |
|---|---|---|
| `net_amount` | Signed net (debit-normal positive, credit-normal positive per `normal_side`) | `SUM(amount)` from `v_fact_lines`, sign-flipped for credit-normal accounts so "spending" and "income" both read as positive in the obvious direction |
| `debit_total` | Sum of debit legs only | `SUM(debit)` |
| `credit_total` | Sum of credit legs only | `SUM(credit)` |
| `entry_count` | Number of lines/entries matched | `COUNT(*)` / `COUNT(DISTINCT entry_id)` |
| `budget_variance` | Actual net vs. `budget_lines` for the same account/period | joins `v_monthly_activity` to `budget_lines` — only valid when `dimension` includes `month` and a budget scenario is selected as the comparison |

`budget_variance` is the one metric that doesn't reduce to a single view
scan — flag it as v2/stretch rather than launch scope.

## Dimension enum (v1, shipped)

| Enum value | Meaning | Source | Value list (for the include/exclude checklist) |
|---|---|---|---|
| `account` | Group by leaf account | `v_fact_lines.account_id/code/name` | `v_dim_account WHERE is_postable` |
| `account_level:N` | Group by ancestor at hierarchy depth N | `fn_rollup_balance` | `account_levels` rows |
| `tag` | Group by tag | unnest `v_fact_lines.tags` | `tags WHERE is_active` |
| `scenario` | Group by scenario | `v_fact_lines.scenario_code` | `scenarios` |
| `month` / `quarter` / `year` | Group by period | `v_fact_lines.month` (bucket further in SQL for quarter/year) | n/a — a period-bucketing choice, not a value list |

v1: **one** dimension at a time (matches a single `GROUP BY`, one
series/axis). v2: a second dimension for the stacked/split-by case shown
in Actual's own UI (e.g. account × month) — still enum × enum, not
arbitrary, but doubles the number of pre-written query shapes to
maintain, so treat as a deliberate follow-up, not part of the same
first cut.

The **value-level include/exclude checklist** (seen in Actual's
category tree: check/uncheck specific leaves, not just pick the
dimension) is worth carrying over from day one — it's a `WHERE
account_id IN (...)` / `WHERE tag_id IN (...)` clause built from a
validated subset of the dimension's own value list, not a new kind of
input.

## Filters (v1, shipped)

All closed/typed, all optional, all AND-combined (no boolean tree):

- **Date range** — `entry_date BETWEEN :from AND :to`, same picker every
  other report page already has.
- **Account (+ subtree toggle)** — filter to one account, optionally
  including all descendants (walk `v_dim_account.path`).
- **Tag** — filter to entries carrying a given tag.
- **Scenario** — defaults to ACTUAL; selectable for what-if comparisons.
- **Payee** — filter to one payee (`v_fact_lines.payee`).
- **Account type** — filter to one of the five `account_type` enum
  values (already a column on `v_fact_lines`, a closed Postgres enum —
  zero new surface). Added in the 2026-08-31 revision: `BACKLOG.md`'s
  graph wishlist is the acceptance test for v1's expressiveness, and
  "expense distribution pie" needs this filter to be expressible
  without relying on the chart of accounts having a single expenses
  root.

## `saved_reports` schema (sketch)

```sql
CREATE TABLE saved_reports (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    owner_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
    -- The whole config is enum values and typed filter parameters, never
    -- SQL or a field name chosen freehand — see Architecture above. Safe
    -- to store and safe to replay unmodified because validation happens
    -- on every GET /reports/custom call, not just at save time.
    metric      TEXT NOT NULL,       -- one of the metric enum values
    dimension   TEXT NOT NULL,       -- one of the dimension enum values
    filters     JSONB NOT NULL DEFAULT '{}',  -- {date_range, account_id, tag_id, scenario_id, payee_id, included_values: [...]}
    chart_type  TEXT NOT NULL DEFAULT 'bar',  -- bar | line | area | pie | table
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`metric`/`dimension`/`chart_type` as `TEXT` rather than a Postgres
`ENUM` type deliberately — matches how `scenarios.scenario_type` vs.
`accounts.account_type` are already split in this schema (the latter is
a real enum because the trigger logic branches on it; report metric/
dimension enums live entirely in the Python layer, so a Python
`Literal`/`Enum` is the actual source of truth and the column just needs
a `CHECK (metric IN (...))` to stay in sync, same pattern as
`scenarios.code`'s format check). No FK to any single "the one true
owner" concept beyond `users` — single-user and multi-user self-hosts
both work unchanged.

## Frontend shape

One page component (shipped: `frontend/src/reports/CustomReportPage.tsx`),
following the "one component per archetype" rule
(`UI_CONSISTENCY_AUDIT.md` §1, `docs/ARCHITECTURE.md`): a config panel
(metric/dimension dropdowns typed against the generated enum unions,
filter controls reusing the existing
`Combobox`/`DatePicker`/`PeriodPresetPicker` widgets, chart-type
toggle) driving a `GET /reports/custom` fetch, with the whole config
URL-state like every sibling report. The value-level include/exclude
checklist described below did not make it into v1 (see Phasing) —
shipped filters are the closed set in "Filters (v1 sketch)" above,
each a single value, not a checklist. Save/load (v2) reuses the
Management/CRUD archetype.

Two assumptions from the original sketch, resolved against the rebuilt
frontend:

- **Charting is a new dependency, not a given.** The frontend's
  dependency list was deliberately tiny (react, react-dom,
  react-router-dom, openapi-fetch — nothing else), so Recharts was its
  first significant UI dependency (plus `react-is`, an unhoisted peer
  dependency npm doesn't install automatically). Decision: use Recharts
  anyway — hand-rolled SVG is a rabbit hole once axes, ticks, tooltips,
  legends, and pies are involved, and the existing widgets' "hand-tuned
  for real browser quirks" philosophy is about *input* components,
  where the quirks live, not about read-only rendering. It cost ~650KB
  gzipped-to-~180KB of bundle growth (899KB total, 251KB gzip) — a
  route-level `React.lazy` split is the obvious follow-up if that
  becomes a problem, not yet done.
- **There is no table-with-subtotals component to reuse.** The hoped-for
  shared Range/period table never got extracted — each report page's
  table is bespoke. Fine for v1: one dimension means one `GROUP BY`, so
  table mode is a flat table plus a total row, no hierarchy machinery
  needed. (The `account_level:N` dimension returns rows already rolled
  up by `fn_rollup_balance` — still flat.)

## Phasing

1. **v1 — shipped 2026-08-31**: one metric + one dimension + the filter
   set above + chart/table toggle, plus `.csv`/`.xlsx` export siblings
   (via the shared `export/` writers, same as every other report). No
   save — but the URL-is-the-config property means any v1 report is
   already shareable/bookmarkable, and is the bridge to v2's saved
   reports. No schema change: no migration, no `saved_reports`, the 60
   invariant tests untouched. Proves the allowlist pattern end-to-end.
   Acceptance check for expressiveness, both met: `BACKLOG.md`'s "Add
   graphs" wishlist's expense/income-distribution pie and net-by-month
   bar/line are expressible as v1 configs (the stacked
   expenses-by-category-per-month bar is genuinely v3, second
   dimension; waterfall is a chart type v1 doesn't have at all — see
   below).
2. **v2 — not started**: `saved_reports` CRUD, the value-level
   include/exclude checklist, dashboard placement for saved reports.
3. **v3 (stretch) — not started**: second dimension (stacked/split-by),
   `budget_variance` metric, a waterfall chart type (`BACKLOG.md`'s
   cash-flow and income-statement waterfalls need this specifically —
   it's a distinct mark type from the bar/line/area/pie set v1 has, not
   just another dimension).

Deliberately not phased in: arbitrary filter trees, ad hoc calculated
fields, a client-side query engine — see Non-goals. If a future need
genuinely can't be expressed as an enum addition, that's a signal to
open a new numbered decision in `SPEC.md` about *why*, not to quietly
grow this into a general query language.
