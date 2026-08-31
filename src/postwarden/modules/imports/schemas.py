"""Pydantic request model for the mapped importer's commit step — the
only route in this module with a JSON body. `POST /import` and `POST
/import/mapped/preview` are both `multipart/form-data` (a real file
upload plus a `target_scenario_id` field), which FastAPI validates
straight from `Form(...)`/`File(...)` parameters in `router.py`; no
Pydantic model earns its keep for either, same reasoning `modules/
reports/router.py`'s own docstring gives for that module having no
`schemas.py` at all."""
from pydantic import BaseModel


class MappedImportCommitRequest(BaseModel):
    """Body of `POST /import/mapped` — the mapping step's Confirm. The
    client round-trips the uploaded file and the two mappings between
    `GET /import/mapped/preview`'s response and this commit step: the
    raw file re-encoded as base64 (`file_content_b64`), plus
    `account_map`/`category_map` dicts for each mapping choice. Nothing
    is ever persisted server-side between the two steps — there's
    nothing to save, expire, or clean up, so the round trip is the
    simplest correct design."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    account_map: dict[str, str] = {}
    category_map: dict[str, str] = {}
    flip_sign: bool = False
