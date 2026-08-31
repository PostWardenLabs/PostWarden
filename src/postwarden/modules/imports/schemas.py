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


class MappedColumnsReparseRequest(BaseModel):
    """Body of `POST /import/mapped/columns/reparse` — the dialect
    panel's own live re-parse (IMPORT_WIZARD.md §7 Phase 2 item 5, R2's
    "the preview is always the file's real data"). Same three
    round-tripped values every step here carries forward, plus the
    dialect the user just edited; `dialect`'s keys are all optional
    (`service.resolve_dialect` fills in anything missing from `service.
    IMPORT_DEFAULT_DIALECT`) so a client only has to send what actually
    changed, though in practice `ImportMappedPanel.tsx` always sends the
    full dict it already holds."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    dialect: dict[str, str | int] = {}


class MappedImportPreviewRequest(BaseModel):
    """Body of `POST /import/mapped/preview` — the column-mapping step's
    own Confirm. `column_map` is target-field-key -> the file's own
    column name for it (`service.IMPORT_MAPPED_FIELDS`' `key`s), chosen
    against the columns/samples `POST /import/mapped/columns` handed
    back. `filename`/`target_scenario_id`/`file_content_b64`/`dialect`
    are the same round-tripped values that step already returned
    (`dialect` possibly user-edited via `/mapped/columns/reparse` along
    the way), carried forward unchanged — nothing is persisted
    server-side between any of these steps, so every step's request body
    is whatever the previous step hasn't finished using yet."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    column_map: dict[str, str] = {}
    dialect: dict[str, str | int] = {}


class MappedImportValidateRequest(BaseModel):
    """Body of `POST /import/mapped/validate` — the review step's own
    pre-commit check (IMPORT_WIZARD.md §7 Phase 3), run with the exact
    account/category maps the user just chose. Same fields `MappedImport
    CommitRequest` carries, minus `skip_bad_rows` — this endpoint's whole
    point is finding out whether that's needed before the frontend has to
    decide it. Never touches the database (`service.validate_mapped`)."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    column_map: dict[str, str] = {}
    dialect: dict[str, str | int] = {}
    account_map: dict[str, str] = {}
    category_map: dict[str, str] = {}
    flip_sign: bool = False


class MappedImportCommitRequest(BaseModel):
    """Body of `POST /import/mapped` — the review step's own Confirm.
    Carries forward the same `column_map`/`dialect` the preview step
    validated (both re-applied on the backend, not trusted from the
    preview response — see `service.import_mapped`'s own docstring) plus
    the two mappings the review step itself collects,
    `account_map`/`category_map`. Nothing is ever persisted server-side
    between any of these steps — there's nothing to save, expire, or
    clean up, so the round trip is the simplest correct design.

    `skip_bad_rows` (IMPORT_WIZARD.md §7 Phase 3 item 2) — defaults to
    `False`: any row error blocks the whole commit unless the caller
    explicitly opts in, once it's actually seen those errors (normally
    via `POST /import/mapped/validate` first — see `service.import_
    mapped`'s own docstring)."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    column_map: dict[str, str] = {}
    dialect: dict[str, str | int] = {}
    account_map: dict[str, str] = {}
    category_map: dict[str, str] = {}
    flip_sign: bool = False
    skip_bad_rows: bool = False
