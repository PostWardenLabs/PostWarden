"""Pydantic request models for the entries module's write routes —
every route here takes a JSON body, unlike `modules/reports/` where
every route is a GET with plain query params FastAPI already validates
from the function signature.

Response shapes stay plain dicts, same convention `modules/reports/`
already established — there's no reference-data picker (scenarios,
accounts, payees, tags) folded into any response here; the frontend
fetches those separately from `modules/reference/`.
"""
from datetime import date

from pydantic import BaseModel


class EntryLineIn(BaseModel):
    """One line of a new entry. `debit`/`credit` stay plain strings, not
    `Decimal` fields: `domain.entry.parse_lines` already does the
    string -> `Decimal` parsing (and the validation messages
    `test_entry.py` covers) against parallel string lists, so giving
    Pydantic its own numeric field here would mean "is this a valid
    amount" gets answered twice, by two different validators, possibly
    disagreeing. The router unzips a `list[EntryLineIn]` back into
    parallel lists before calling `parse_lines`, so the parsing logic
    itself stays untouched."""
    account: str
    debit: str = ""
    credit: str = ""
    memo: str | None = None


class CreateEntryRequest(BaseModel):
    """Body of `POST /entries`. `entry_date` defaults to today when
    omitted — done in `service.create_entry`, not here, since "today" is
    a runtime fact, not a request-shape one. `created_by_user_id` is
    deliberately not a field: that's set from the session, not from
    anything the client sends — see `router.py`'s own docstring."""
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
    every given entry. The bulk 'Edit tags' popup fires one of these per
    chip added/removed rather than batching a set of changes behind a
    Save button."""
    entry_ids: list[str]
    action: str
    tag: str


class EditDescriptionRequest(BaseModel):
    """Body of `POST /entries/{entry_id}/edit-description`."""
    description: str


class EditMemoRequest(BaseModel):
    """Body of `POST /entries/lines/{line_id}/edit-memo`."""
    memo: str | None = None
