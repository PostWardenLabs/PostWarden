"""Pydantic request models for the reference module's write routes —
Accounts, Account levels, Scenarios, Payees, Tags. Same convention
`modules/entries/schemas.py` established: response shapes stay plain
dicts (`repository.py`'s own), only request bodies get a model.

`account_type`/`scenario_type` are `Literal`s here, matching `db/
schema.sql`'s own `account_type`/`scenario_type` enums exactly — FastAPI
turns an invalid value into a 422 automatically, which is what replaces
legacy `quick_create_account`'s manual `if acct_type not in
ACCOUNT_TYPES` check (see `repository.py`'s own docstring)."""
from typing import Literal

from pydantic import BaseModel

AccountType = Literal["asset", "liability", "equity", "income", "expense"]
ScenarioType = Literal["actual", "budget", "forecast", "what_if"]


class CreateAccountRequest(BaseModel):
    """Body of `POST /accounts`."""
    code: str
    name: str
    account_type: AccountType
    parent_id: int | None = None
    is_postable: bool = False
    is_cashflow: bool = False


class QuickCreateAccountRequest(BaseModel):
    """Body of `POST /accounts/quick-create` — the accounts.html "+"
    picker. Exactly one of `parent_id`/`account_type` drives the new
    leaf's type (`parent_id` wins when both are given, same as legacy);
    the code itself is generated, not supplied."""
    name: str
    parent_id: int | None = None
    account_type: AccountType | None = None
    is_postable: bool = False


class CreateAccountLevelRequest(BaseModel):
    """Body of `POST /account-levels`."""
    name: str
    depth: int


class RenameRequest(BaseModel):
    """Body shared by every plain `{id}/rename` route in this module
    (account levels, payees, tags) — all three ever needed was a new
    name."""
    name: str


class CreateScenarioRequest(BaseModel):
    """Body of `POST /scenarios`."""
    code: str
    name: str
    scenario_type: ScenarioType
    enforce_balance: bool = True
    income_statement_only: bool = False
    base_level_id: int | None = None
    notes: str | None = None


class CreatePayeeRequest(BaseModel):
    """Body shared by `POST /payees` and `POST /payees/quick-create` —
    both ever needed was a name; the two routes differ only in whether a
    duplicate reactivates instead of erroring (see `service.py`)."""
    name: str


class MergePayeesRequest(BaseModel):
    """Body of `POST /payees/merge`. `payee_ids[0]` is the survivor —
    which one survives is otherwise arbitrary, since `target_name` is set
    explicitly afterward regardless (ported from `merge_payees`)."""
    payee_ids: list[int]
    target_name: str


class CreateTagRequest(BaseModel):
    """Body of `POST /tags` — goes through `domain.entry.parse_tags` in
    `service.py`, same validation/lowercasing a chip-input's comma string
    gets, requiring exactly one name."""
    name: str


class MergeTagsRequest(BaseModel):
    """Body of `POST /tags/merge`. Same survivor-is-first-id shape as
    `MergePayeesRequest` — see its own docstring."""
    tag_ids: list[int]
    target_name: str
