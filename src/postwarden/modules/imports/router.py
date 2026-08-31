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

**The mapped importer is a three-step wizard, upload -> map columns ->
review, and only the first step is a real file upload.** `GET
/import/mapped` itself doesn't exist here at all — that page's only
content beyond this module is the scenario picker, a `modules/
reference/` concern. `POST /import/mapped/columns` takes the multipart
upload and returns the file's own column names/sample rows (`service.
sniff_mapped_columns`) plus its content, base64-encoded (`service.
encode_for_roundtrip`) — the frontend holds that in memory and sends it
back verbatim as each later step's own `file_content_b64`, same
round-trip `schemas.py`'s own docstring already explains. `POST
/import/mapped/preview` takes that plus the column-mapping step's own
choices (JSON, `schemas.MappedImportPreviewRequest`) and returns the
review step's picker lists; `POST /import/mapped` takes the review
step's own Account/Category choices and actually commits."""
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


@router.post("/mapped/columns", dependencies=[Depends(require_csrf_header)])
async def import_mapped_columns(target_scenario_id: int = Form(...), file: UploadFile = File(...)) -> dict:
    """No `conn`/database at all — sniffing a file's own column names is
    pure (`service.sniff_mapped_columns`). `fields` is `service.
    IMPORT_MAPPED_FIELDS` verbatim, so the mapping step's own target-field
    list lives in exactly one place; `target_scenario_id`/`filename` are
    handed back unchanged alongside `file_content_b64` purely so the
    frontend can carry them forward through the rest of the wizard
    without holding separate state of its own."""
    raw = await file.read()
    try:
        content = service.decode_upload(raw)
        sniff = service.sniff_mapped_columns(content)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **sniff,
        "fields": service.IMPORT_MAPPED_FIELDS,
        "filename": file.filename or "import.csv",
        "target_scenario_id": target_scenario_id,
        "file_content_b64": service.encode_for_roundtrip(raw),
    }


@router.post("/mapped/preview", dependencies=[Depends(require_csrf_header)])
def import_mapped_preview(payload: schemas.MappedImportPreviewRequest) -> dict:
    """No `conn`/database at all — parsing and grouping the file's own
    Account/Category values (once mapped onto real columns via `payload.
    column_map`) is pure (`service.preview_mapped`). `filename`/
    `target_scenario_id`/`file_content_b64`/`column_map` are all handed
    back unchanged so the frontend can carry them forward into the
    commit step without holding separate state of its own — same
    round-trip-everything-forward shape the old multipart version of
    this route already had."""
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        preview = service.preview_mapped(content, payload.column_map)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **preview,
        "filename": payload.filename,
        "target_scenario_id": payload.target_scenario_id,
        "file_content_b64": payload.file_content_b64,
        "column_map": payload.column_map,
    }


@router.post("/mapped")
def import_mapped_commit(payload: schemas.MappedImportCommitRequest,
                          session: dict = Depends(require_csrf_header),
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        result = service.import_mapped(
            conn, content=content, filename=payload.filename,
            target_scenario_id=payload.target_scenario_id, column_map=payload.column_map,
            account_map=payload.account_map, category_map=payload.category_map,
            flip_sign=payload.flip_sign, user_id=session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return result
