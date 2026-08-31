"""Pydantic request models for the entries module's write routes — the
one module REBUILD.md decision 3 names explicitly as needing a
`schemas.py`, unlike `modules/reports/` (every route there is a GET with
plain query params FastAPI already validates from the function
signature; every route here takes a JSON body instead).

Response shapes stay plain dicts, same convention `modules/reports/`
already established — there's no reference-data picker (scenarios,
accounts, payees, tags) folded into any response here either, same
"don't reach into a module that doesn't exist yet" reasoning
`modules/reports/router.py`'s own docstring applies to
`modules/reference/` (Phase 1.9): the frontend fetches those separately.
"""
from datetime import date

from pydantic import BaseModel


class EntryLineIn(BaseModel):
    """One line of a new entry. `debit`/`credit` stay plain strings, not
    `Decimal` fields — the one deliberate shape change from legacy's
    parallel `account[]`/`debit[]`/`credit[]`/`memo[]` form arrays, which
    only existed because an HTML `<form>` has no way to express "a list
    of line objects." `domain.entry.parse_lines` already does exactly
    the string -> `Decimal` parsing (and the validation messages
    `test_entry.py` covers) against parallel string lists; giving
    Pydantic its own numeric field here would mean "is this a valid
    amount" gets answered twice, by two different validators, possibly
    disagreeing. The router unzips a `list[EntryLineIn]` back into
    parallel lists immediately before calling `parse_lines`, so the
    parsing logic itself is untouched."""
    account: str
    debit: str = ""
    credit: str = ""
    memo: str | None = None


class CreateEntryRequest(BaseModel):
    """Body of `POST /entries`. `entry_date` defaults to today when
    omitted, same as legacy's `form.get("entry_date") or
    date.today().isoformat()` — done in `service.create_entry`, not here,
    since "today" is a runtime fact, not a request-shape one.
    `created_by_user_id` is deliberately not a field: that's set from the
    session once `modules/auth/` (Phase 1.11) exists, not from anything
    the client sends — see `router.py`'s own docstring."""
    entry_date: date | None = None
    scenario_id: int
    description: str
    reference: str | None = None
    payee_id: int | None = None
    tags: str = ""
    lines: list[EntryLineIn]


class ReverseEntriesRequest(BaseModel):
    """Body of `POST /entries/reverse` — the Journal's bulk reversal."""
    entry_ids: list[str]


class EditTagsRequest(BaseModel):
    """Body of `POST /entries/tags` — one tag, added to or removed from
    every given entry. Same shape as legacy's bulk 'Edit tags' popup,
    which fires one of these per chip added/removed rather than batching
    a set of changes behind a Save button."""
    entry_ids: list[str]
    action: str
    tag: str


class EditDescriptionRequest(BaseModel):
    """Body of `POST /entries/{entry_id}/edit-description`."""
    description: str


class EditMemoRequest(BaseModel):
    """Body of `POST /entries/lines/{line_id}/edit-memo`."""
    memo: str | None = None
