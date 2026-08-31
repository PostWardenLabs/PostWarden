"""Pydantic request models for the mapped importer's own three-step
wizard (upload -> map columns -> review Account/Category -> commit).
`POST /import` and `POST /import/mapped/columns` are the only
`multipart/form-data` routes left (a real file upload plus a
`target_scenario_id` field), which FastAPI validates straight from
`Form(...)`/`File(...)` parameters in `router.py`; every step after the
initial upload is JSON, since there's no file to carry beyond that
point — just `file_content_b64`, already-parsed strings and dicts,
round-tripped as plain JSON same as everywhere else in this app."""
from pydantic import BaseModel


class MappedImportPreviewRequest(BaseModel):
    """Body of `POST /import/mapped/preview` — the column-mapping step's
    own Confirm. `column_map` is target-field-key -> the file's own
    column name for it (`service.IMPORT_MAPPED_FIELDS`' `key`s), chosen
    against the columns/samples `POST /import/mapped/columns` handed
    back. `filename`/`target_scenario_id`/`file_content_b64` are the same
    three round-tripped values that step already returned, carried
    forward unchanged — nothing is persisted server-side between any of
    these steps, so every step's request body is whatever the previous
    step hasn't finished using yet."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    column_map: dict[str, str] = {}


class MappedImportCommitRequest(BaseModel):
    """Body of `POST /import/mapped` — the review step's own Confirm.
    Carries forward the same `column_map` the preview step validated
    (re-applied on the backend, not trusted from the preview response —
    see `service.import_mapped`'s own docstring) plus the two mappings
    the review step itself collects, `account_map`/`category_map`.
    Nothing is ever persisted server-side between any of these steps —
    there's nothing to save, expire, or clean up, so the round trip is
    the simplest correct design."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    column_map: dict[str, str] = {}
    account_map: dict[str, str] = {}
    category_map: dict[str, str] = {}
    flip_sign: bool = False
