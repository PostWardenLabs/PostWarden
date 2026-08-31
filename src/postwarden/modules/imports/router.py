"""The imports module's `APIRouter` — both importers (plain CSV,
mapped/rules). Same shape every prior module's own router established:
thin routes, real logic in `service.py`.

`get_current_session` is required at the router level for every route,
every write route additionally requires `require_csrf_header`, and both
`import_csv` and `import_mapped_commit` bind the resulting `session` to
thread `session["user_id"]` through as `imported_by_user_id`.
`import_mapped_columns`/`import_mapped_preview` need the CSRF check too
but never touch attribution — neither writes anything — so they only
gain `require_csrf_header` as a bare `dependencies=[...]` entry, not a
bound parameter. No target-scenario picker payload on `GET /import`
either — that's a `modules/reference/` concern, same as every prior
module.

**The mapped importer is a wizard, upload -> shape + dialect + map
columns -> review value maps -> commit, and only the first step is a
real file upload.** `GET /import/mapped` itself doesn't exist here at
all — that page's only content beyond this module is the scenario
picker, a `modules/reference/` concern. `POST /import/mapped/columns`
takes the multipart upload and returns the file's own column names/
sample rows (`service.sniff_mapped_columns`), a best-guess `shape`
(`service.sniff_shape`, IMPORT_WIZARD.md §7 Phase 4 item 1) plus every
shape's own target-field list precomputed (`service.target_fields_by_
shape` — so the frontend's own shape toggle never needs a round trip),
and its content, base64-encoded (`service.encode_for_roundtrip`) — the
frontend holds all of this in memory and sends the relevant parts back
verbatim as each later step's own request body, same round-trip
`schemas.py`'s own docstring already explains. `POST /import/mapped/
preview` takes that plus the column-mapping step's own choices (JSON,
`schemas.MappedImportPreviewRequest`) and returns the review step's
lookup-table contents; `POST /import/mapped` takes the review step's own
value-map choices and actually commits.

**`POST /import/mapped/columns/reparse` isn't a fourth wizard step** —
it's the dialect panel living inside the "columns" step (IMPORT_WIZARD.md
§7 Phase 2), re-parsing the same already-uploaded file against a
user-edited dialect instead of the one `/mapped/columns` guessed. Every
later step (`/mapped/preview`, `/mapped/validate`, `/mapped`) also takes
that same `dialect` forward and re-applies it server-side, same "never
trust caller-supplied structure without re-deriving it" reasoning
`column_map`/`shape`/`column_kinds` already get. `shape` never triggers a
re-parse here (see `schemas.MappedColumnsReparseRequest`'s own
docstring) — only `dialect` can change how the file's own cells split.

**`POST /import/mapped/validate` isn't a fifth step either** — it's the
review step's own pre-commit check (IMPORT_WIZARD.md §7 Phase 3), run
with the value maps the review step just collected, before `POST
/import/mapped` actually commits anything. A row error there now blocks
`/mapped` outright unless the caller sets `skip_bad_rows` (see
`schemas.MappedImportCommitRequest`'s own docstring) — the frontend's own
flow is to call `/mapped/validate` first, show a validation-report screen
only when it comes back with any errors, and only then let the user
choose to stage the rest and skip them.

**Both `/mapped/validate` and `POST /mapped` do one bulk DB lookup before
calling into the otherwise-pure `service.validate_file`/`service.import_
file`** — `service.known_account_codes`, whenever `payload.column_kinds`
marks any field `"code"` (IMPORT_WIZARD.md §7 Phase 4 item 2's own
"restore the per-row unknown-code diagnostic without giving the pure
functions a `Connection`" design; see that function's own docstring).
`/mapped/preview` never needs this — it doesn't resolve accounts at all,
only lists the raw values a `"label"`-kind column would need mapped."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...db import get_connection
from ...errors import pg_message
from ..auth.deps import get_current_session, require_csrf_header
from . import schemas, service

router = APIRouter(prefix="/import", tags=["imports"],
                    dependencies=[Depends(get_current_session)])


@router.get("")
def recent_batches(limit: int = 10, conn: Connection = Depends(get_connection)) -> dict:
    return {"recent_batches": service.recent_batches(conn, limit)}


@router.post("")
async def import_csv(target_scenario_id: int = Form(...), file: UploadFile = File(...),
                      session: dict = Depends(require_csrf_header),
                      conn: Connection = Depends(get_connection)) -> dict:
    """Unchanged multipart contract (IMPORT_WIZARD.md §7 Phase 4 item 4)
    — only `service.import_csv`'s own internals moved onto the unified
    pipeline, a thin shim now rather than its own parsing logic. Retired
    outright in Phase 4 item 5 once `ImportPlainPanel.tsx` stops calling
    it."""
    try:
        content = service.decode_upload(await file.read())
        result = service.import_csv(
            conn, content=content, filename=file.filename or "import.csv",
            target_scenario_id=target_scenario_id, user_id=session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return result


def _known_codes_if_needed(conn: Connection, content: str, shape: dict, column_map: dict[str, str],
                            column_kinds: dict[str, str], dialect: dict) -> set[str] | None:
    """Shared by `/mapped/validate` and `POST /mapped` — see this
    module's own docstring. A thin wrapper, not `service.known_account_
    codes` itself, purely so neither route has to repeat the "only makes
    sense once some column is `code`-kind" framing inline."""
    if service.IMPORT_COLUMN_KIND_CODE not in column_kinds.values():
        return None
    return service.known_account_codes(conn, content, shape, column_map, column_kinds, dialect)


@router.post("/mapped/columns", dependencies=[Depends(require_csrf_header)])
async def import_mapped_columns(target_scenario_id: int = Form(...), file: UploadFile = File(...)) -> dict:
    """No `conn`/database at all — sniffing a file's own column names,
    its dialect, and its shape is pure (`service.sniff_mapped_columns`,
    `service.sniff_dialect`, `service.sniff_shape`). `fields_by_shape`/
    `delimiters`/`date_formats` are `service`'s own canonical lists
    verbatim, so the mapping step's target-field lists and the dialect
    panel's own option lists each live in exactly one place;
    `target_scenario_id`/`filename` are handed back unchanged alongside
    `file_content_b64` purely so the frontend can carry them forward
    through the rest of the wizard without holding separate state of its
    own. `dialect`/`shape` are both *guesses* (R1) — the frontend's own
    panels start from them, and `POST /import/mapped/columns/reparse` is
    what a user's dialect edit re-parses against (a shape edit needs no
    re-parse at all, see that route's own docstring)."""
    raw = await file.read()
    try:
        content = service.decode_upload(raw)
        dialect = service.sniff_dialect(content)
        sniff = service.sniff_mapped_columns(content, dialect)
        shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **sniff,
        "dialect": dialect,
        "shape": shape,
        "delimiters": service.IMPORT_DELIMITERS,
        "date_formats": service.IMPORT_DATE_FORMATS,
        "fields_by_shape": service.target_fields_by_shape(),
        "filename": file.filename or "import.csv",
        "target_scenario_id": target_scenario_id,
        "file_content_b64": service.encode_for_roundtrip(raw),
    }


@router.post("/mapped/columns/reparse", dependencies=[Depends(require_csrf_header)])
def import_mapped_columns_reparse(payload: schemas.MappedColumnsReparseRequest) -> dict:
    """The dialect panel's own live re-parse — same shape `/mapped/
    columns` returns (minus `delimiters`/`date_formats`/`fields_by_
    shape`/`shape` itself, which are either static option lists the
    frontend already has from the first call or a setting a dialect edit
    never invalidates — see `schemas.MappedColumnsReparseRequest`'s own
    docstring), against a user-edited `dialect` rather than a freshly
    sniffed one. No sniffing here — a dialect the user just chose is
    trusted as-is, not re-guessed out from under them the moment they
    touch a control."""
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        dialect = service.resolve_dialect(payload.dialect)
        sniff = service.sniff_mapped_columns(content, dialect)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **sniff,
        "dialect": dialect,
        "filename": payload.filename,
        "target_scenario_id": payload.target_scenario_id,
        "file_content_b64": payload.file_content_b64,
    }


@router.post("/mapped/preview", dependencies=[Depends(require_csrf_header)])
def import_mapped_preview(payload: schemas.MappedImportPreviewRequest) -> dict:
    """No `conn`/database at all — parsing the file's own rows (once
    mapped onto real columns via `payload.column_map`, split by
    `payload.dialect`) and collecting each `"label"`-kind lookup column's
    distinct values is pure (`service.preview_file`). `filename`/
    `target_scenario_id`/`file_content_b64`/`shape`/`column_map`/
    `column_kinds`/`dialect` are all handed back unchanged so the
    frontend can carry them forward into the review/commit steps without
    holding separate state of its own — same round-trip-everything-
    forward shape this route has always had."""
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        dialect = service.resolve_dialect(payload.dialect)
        preview = service.preview_file(content, payload.shape, payload.column_map, payload.column_kinds, dialect)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **preview,
        "filename": payload.filename,
        "target_scenario_id": payload.target_scenario_id,
        "file_content_b64": payload.file_content_b64,
        "shape": payload.shape,
        "column_map": payload.column_map,
        "column_kinds": payload.column_kinds,
        "dialect": dialect,
    }


@router.post("/mapped/validate", dependencies=[Depends(require_csrf_header)])
def import_mapped_validate(payload: schemas.MappedImportValidateRequest,
                            conn: Connection = Depends(get_connection)) -> dict:
    """The review step's own pre-commit check (`service.validate_file`),
    run with the exact value maps the user just chose, same `dialect`
    re-application every other step here does — plus one bulk DB lookup
    (`_known_codes_if_needed`, see this module's own docstring) when any
    lookup column is `"code"`-kind, restoring per-row "unknown account
    code" precision for it. Not a fourth wizard step (same reasoning
    `/mapped/columns/reparse` already documents) — a clean file's
    `errors` comes back empty and the frontend skips straight to `POST
    /import/mapped` without ever showing a validation-report screen
    (R1). Now takes a `conn` (unlike before Phase 4) purely for that one
    lookup — `service.validate_file` itself still never sees it, still
    never writes anything; same "every route pays for a transaction
    uniformly, even a read-only one" reasoning `get_connection`'s own
    docstring already gives, now actually exercised here for a real read."""
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        dialect = service.resolve_dialect(payload.dialect)
        known_codes = _known_codes_if_needed(
            conn, content, payload.shape, payload.column_map, payload.column_kinds, dialect)
        result = service.validate_file(content, payload.shape, payload.column_map, payload.column_kinds,
                                        payload.value_maps, payload.flip_sign, dialect, known_codes)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **result,
        "filename": payload.filename,
        "target_scenario_id": payload.target_scenario_id,
        "file_content_b64": payload.file_content_b64,
        "shape": payload.shape,
        "column_map": payload.column_map,
        "column_kinds": payload.column_kinds,
        "dialect": dialect,
        "value_maps": payload.value_maps,
        "flip_sign": payload.flip_sign,
    }


@router.post("/mapped")
def import_mapped_commit(payload: schemas.MappedImportCommitRequest,
                          session: dict = Depends(require_csrf_header),
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        dialect = service.resolve_dialect(payload.dialect)
        known_codes = _known_codes_if_needed(
            conn, content, payload.shape, payload.column_map, payload.column_kinds, dialect)
        result = service.import_file(
            conn, content=content, filename=payload.filename,
            target_scenario_id=payload.target_scenario_id, shape=payload.shape, column_map=payload.column_map,
            column_kinds=payload.column_kinds, value_maps=payload.value_maps, flip_sign=payload.flip_sign,
            dialect=dialect, skip_bad_rows=payload.skip_bad_rows, known_codes=known_codes,
            user_id=session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return result
