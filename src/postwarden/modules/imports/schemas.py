"""Pydantic request models for the import wizard's own steps (upload ->
shape + dialect + map columns -> review value maps -> commit). `POST
/import/mapped/columns` is the only `multipart/form-data` route left (a
real file upload plus a `target_scenario_id` field), which FastAPI
validates straight from `Form(...)`/`File(...)` parameters in
`router.py`; every step after the initial upload is JSON, since there's
no file to carry beyond that point — just `file_content_b64`,
already-parsed strings and dicts, round-tripped as plain JSON same as
everywhere else in this app."""
from pydantic import BaseModel


class MappedColumnsReparseRequest(BaseModel):
    """Body of `POST /import/mapped/columns/reparse` — the dialect
    panel's own live re-parse (SPEC.md decision 23, R2's
    "the preview is always the file's real data"). Same three
    round-tripped values every step here carries forward, plus the
    dialect the user just edited; `dialect`'s keys are all optional
    (`service.resolve_dialect` fills in anything missing from `service.
    IMPORT_DEFAULT_DIALECT`) so a client only has to send what actually
    changed, though in practice `ImportMappedPanel.tsx` always sends the
    full dict it already holds.

    No `shape` here — editing `shape` (SPEC.md decision
    24) never needs a re-parse of the file itself, only `dialect`'s
    delimiter/header-row does (`service.sniff_shape`'s own docstring);
    it's a client-side-only setting that changes which target fields
    `POST /import/mapped/preview` accepts, not anything about how the
    file's cells get split."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    dialect: dict[str, str | int] = {}


class MappedImportPreviewRequest(BaseModel):
    """Body of `POST /import/mapped/preview` — the column-mapping step's
    own Confirm. `shape` (`service.IMPORT_DEFAULT_SHAPE`'s keys — see
    SPEC.md decision 24) decides which target fields exist
    at all (`service.target_fields_for_shape`); `column_map` is
    target-field-key -> the file's own column name for it, chosen against
    the columns/samples `POST /import/mapped/columns` handed back;
    `column_kinds` (target-field-key -> `"code"`|`"label"`, SPEC.md
    decision 24) says whether each `lookup_capable` field's column
    already holds a real account code or a label needing a lookup table
    in the review step. `filename`/`target_scenario_id`/`file_content_b64`/`dialect`
    are the same round-tripped values that step already returned
    (`dialect` possibly user-edited via `/mapped/columns/reparse` along
    the way), carried forward unchanged — nothing is persisted
    server-side between any of these steps, so every step's request body
    is whatever the previous step hasn't finished using yet."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    shape: dict[str, str | None] = {}
    column_map: dict[str, str] = {}
    column_kinds: dict[str, str] = {}
    dialect: dict[str, str | int] = {}


class MappedImportValidateRequest(BaseModel):
    """Body of `POST /import/mapped/validate` — the review step's own
    pre-commit check (SPEC.md decision 23), run with the exact
    value maps the user just chose. Same fields `MappedImportCommit
    Request` carries, minus `skip_bad_rows` — this endpoint's whole point
    is finding out whether that's needed before the frontend has to
    decide it. Never touches the database itself (`service.validate_
    file`) — see `router.py`'s own docstring on the one bulk `known_
    codes` lookup this route does before calling it."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    shape: dict[str, str | None] = {}
    column_map: dict[str, str] = {}
    column_kinds: dict[str, str] = {}
    dialect: dict[str, str | int] = {}
    value_maps: dict[str, dict[str, str]] = {}
    flip_sign: bool = False


class MappedImportCommitRequest(BaseModel):
    """Body of `POST /import/mapped` — the review step's own Confirm.
    Carries forward the same `shape`/`column_map`/`column_kinds`/
    `dialect` the preview/validate steps used (all re-applied on the
    backend, not trusted from an earlier response — see `service.import_
    file`'s own docstring) plus `value_maps`, the review step's own
    lookup tables (one per `lookup_capable` field whose `column_kinds`
    says `"label"` — generalizes the old, separate `account_map`/
    `category_map` fields into one dict, SPEC.md decision 24). Nothing is
    ever persisted server-side between any of these steps — there's
    nothing to save, expire, or clean up, so the round trip is the
    simplest correct design.

    `skip_bad_rows` (SPEC.md decisions 23–24 — confirmed to apply to
    every shape in the wizard merge) — defaults to `False`: any row
    error blocks the whole commit unless the caller explicitly opts in, once
    it's actually seen those errors (normally via `POST /import/mapped/
    validate` first — see `service.import_file`'s own docstring)."""
    filename: str
    target_scenario_id: int
    file_content_b64: str
    shape: dict[str, str | None] = {}
    column_map: dict[str, str] = {}
    column_kinds: dict[str, str] = {}
    dialect: dict[str, str | int] = {}
    value_maps: dict[str, dict[str, str]] = {}
    flip_sign: bool = False
    skip_bad_rows: bool = False
