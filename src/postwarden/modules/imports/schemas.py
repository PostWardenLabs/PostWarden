"""Pydantic request model for the mapped importer's commit step — the
only route in this module with a JSON body. `POST /import` and `POST
/import/mapped/preview` are both `multipart/form-data` (a real file
upload plus a `target_scenario_id` field), which FastAPI validates
straight from `Form(...)`/`File(...)` parameters in `router.py`; no
Pydantic model earns its keep for either, same reasoning `modules/
reports/schemas.py`'s absence gives for its all-GET/query-param shape."""
from pydantic import BaseModel


class MappedImportCommitRequest(BaseModel):
    """Body of `POST /import/mapped` — the mapping step's Confirm. Legacy
    round-trips the uploaded file and the two mappings between `GET
    /import/mapped/preview`'s response and this commit step as hidden
    `<form>` fields: the raw file re-encoded as base64 (`file_b64`), and
    `account_map__<key>`/`category_map__<key>`-prefixed fields for each
    mapping choice (`form.multi_items()`'s own prefix-strip loop in
    `import_mapped_commit`). Nothing is ever persisted server-side
    between the two steps either way — same "there's nothing to save,
    expire, or clean up" reasoning `app/main.py`'s own comment on this
    importer gives — this is just that same round-trip JSON-shaped
    instead of form-field-name-shaped, the identical adaptation `modules.
    staging.schemas.MergeDuplicatesRequest.line_memos` already made for
    its own prefixed-form-field precursor (`memo_<line_id>`)."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    account_map: dict[str, str] = {}
    category_map: dict[str, str] = {}
    flip_sign: bool = False
