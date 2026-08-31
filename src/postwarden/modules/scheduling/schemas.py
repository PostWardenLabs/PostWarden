"""Pydantic request models for the scheduling module's write routes —
same convention `modules/entries/schemas.py`/`modules/staging/
schemas.py` established. `EntryLineIn` is a byte-for-byte fork of those
modules' own class, not an import — same "a module should be deletable
on its own" reasoning `repository.py`'s docstring gives for every other
forked helper in this module.

`IntervalUnit` mirrors `modules/reference/schemas.py`'s own `Literal`
convention for a DB `CHECK`-constrained enum (`scheduled_entries.
interval_unit IN ('day', 'week', 'month')`, `db/schema.sql`) — a bad
value is a 422 from FastAPI/Pydantic directly, so `service.py` doesn't
need to validate it itself."""
from datetime import date
from typing import Literal

from pydantic import BaseModel

IntervalUnit = Literal["day", "week", "month"]


class EntryLineIn(BaseModel):
    """One line of a schedule or a template. See `modules.entries.
    schemas.EntryLineIn`'s own docstring for why `debit`/`credit` stay
    plain strings rather than `Decimal` fields — `domain.entry.parse_
    lines` already owns that parsing."""
    account: str
    debit: str = ""
    credit: str = ""
    memo: str | None = None


class CreateScheduleRequest(BaseModel):
    """Body of `POST /scheduled`. `next_date` defaults to today when
    omitted — applied in `service.create_schedule`, not here, for
    the same "today is a runtime fact, not a request-shape one" reason
    `modules.entries.schemas.CreateEntryRequest` gives for its own
    `entry_date`. `target_scenario_id` names the column directly
    (`scheduled_entries.target_scenario_id`) rather than reusing
    `modules.entries.schemas.CreateEntryRequest`'s plain `scenario_id` —
    a schedule's occurrences never post to a scenario of their own
    (they always land in Staging first, SPEC.md decision 9), so
    "target" is doing real, load-bearing work here that it wouldn't for
    a Journal entry."""
    description: str
    reference: str | None = None
    payee_id: int | None = None
    target_scenario_id: int
    interval_unit: IntervalUnit
    interval_count: int = 1
    next_date: date | None = None
    tags: str = ""
    lines: list[EntryLineIn]


class CreateTemplateRequest(BaseModel):
    """Body of `POST /templates`. Unlike `CreateScheduleRequest`, no
    scenario field at all — entry templates aren't scenario-bound (see
    `repository.py`'s own comment on `templates_full`)."""
    name: str
    description: str
    reference: str | None = None
    payee_id: int | None = None
    tags: str = ""
    lines: list[EntryLineIn]
