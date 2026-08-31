"""Pydantic request models for the staging module's write routes — same
role `modules/entries/schemas.py` plays for the Journal. `EntryLineIn`
is a byte-for-byte fork of that module's own class, not an import — see
`repository.py`'s docstring for why this module forks rather than
imports across the vertical-slice boundary."""
from datetime import date

from pydantic import BaseModel


class EntryLineIn(BaseModel):
    """One line of a staged entry being edited. See `modules.entries.
    schemas.EntryLineIn`'s own docstring for why `debit`/`credit` stay
    plain strings rather than `Decimal` fields — `domain.entry.parse_
    lines` already owns that parsing."""
    account: str
    debit: str = ""
    credit: str = ""
    memo: str | None = None


class ApproveRejectRequest(BaseModel):
    """Body of both `POST /staging/approve` and `POST /staging/reject` —
    same shape, since both are "act on this checked set" over the same
    selection."""
    entry_ids: list[str]


class EditStagingEntryRequest(BaseModel):
    """Body of `POST /staging/{entry_id}/edit` — the inline edit panel's
    Save. `entry_date` defaults to today when omitted — applied in
    `service.save_edit` rather than here, same reasoning `modules.
    entries.schemas.CreateEntryRequest` gives: "today" is a runtime
    fact, not a request-shape one."""
    entry_date: date | None = None
    description: str
    reference: str | None = None
    payee_id: int | None = None
    tags: str = ""
    lines: list[EntryLineIn]


class MergeDuplicatesRequest(BaseModel):
    """Body of `POST /staging/duplicates/merge`. `line_memos` is keyed by
    line id as a string (JSON object keys are always strings) — the
    router looks up each of the survivor's own line ids in this dict,
    and a missing key just leaves that line's memo untouched rather than
    clearing it."""
    keep_id: str
    remove_ids: list[str]
    description: str
    reference: str | None = None
    payee_id: int | None = None
    tags: str = ""
    line_memos: dict[str, str] = {}
