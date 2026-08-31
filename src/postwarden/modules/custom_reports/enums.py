"""The closed allowlists a custom report is composed from — the entire
vocabulary a client can send (`CUSTOM_REPORTS.md`'s Architecture
section). Because these are the route signature's own types
(`router.py`), FastAPI 422s anything outside them before any code runs,
and the generated frontend client (`frontend/src/api/schema.ts`)
exposes them as TypeScript union types — adding a member here without
handling it frontend-side is a `tsc` error, which is why no runtime
"schema" endpoint exists.

Adding a metric or dimension means adding an enum member *and* its
fragment in `repository.py`'s `_METRICS`/`_DIMENSIONS` — never a
free-form field name from the client. If a wanted report can't be
expressed as a member here, that's a signal to revisit
`CUSTOM_REPORTS.md`'s Non-goals, not to loosen the enum.

`AccountTypeFilter` mirrors the Postgres `account_type` enum
(`db/schema.sql`) rather than importing anything — the two are kept in
sync by `apitests/modules/custom_reports/`'s own check against the
live enum, the same Python-is-the-source-of-truth stance
`CUSTOM_REPORTS.md`'s `saved_reports` sketch takes for metric/dimension.
"""
from enum import Enum


class Metric(str, Enum):
    """What gets aggregated — each member maps to exactly one SELECT
    fragment in `repository._METRICS`."""
    net_amount = "net_amount"
    debit_total = "debit_total"
    credit_total = "credit_total"
    entry_count = "entry_count"


class Dimension(str, Enum):
    """What the metric is grouped by — each member maps to exactly one
    GROUP BY shape in `repository._DIMENSIONS`. `account_level` is the
    doc's `account_level:N` split into an enum member plus a separate
    validated `level_id` query param (the same shape Variance's own
    `level_id` takes), so the enum itself stays closed."""
    account = "account"
    account_level = "account_level"
    tag = "tag"
    scenario = "scenario"
    month = "month"
    quarter = "quarter"
    year = "year"


class AccountTypeFilter(str, Enum):
    """The five `account_type` enum values, as a typed filter."""
    asset = "asset"
    liability = "liability"
    equity = "equity"
    income = "income"
    expense = "expense"
