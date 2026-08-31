"""Pydantic request model for the budget module's one write route. Same
role `modules/entries/schemas.py`/`modules/staging/schemas.py` play for
their own modules — this module needs exactly one, since `GET /budget` is
plain query params FastAPI already validates from the route signature."""
from datetime import date

from pydantic import BaseModel


class SaveCellRequest(BaseModel):
    """Body of `POST /budget/cell` — one grid cell's new value. `amount`
    stays a plain string, not a Pydantic `Decimal` field — see
    `service.save_budget_cell`'s own docstring for why. `period_month` is
    a real `date`, same as `modules.entries.schemas.CreateEntryRequest`'s
    own `entry_date` — always the first of the month the grid is
    currently showing (`budget_grid`'s own `month_start`), so unlike
    `entry_date` there's no "defaults to today" case to leave optional."""
    scenario_id: int
    account: str
    period_month: date
    amount: str = ""
