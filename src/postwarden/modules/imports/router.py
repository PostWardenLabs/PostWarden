"""The imports module's `APIRouter` — both importers (plain CSV,
mapped/rules). Same shape every prior module's own router established:
thin routes, real logic in `service.py`.

Mounted into `app` as of Phase 1.14 (`main.py`), which closes the gap
this docstring used to flag: every route now requires `get_current_
session` (router-level, legacy's global `auth_gate` equivalent), every
write route additionally requires `require_csrf_header`, and both
`import_csv` and `import_mapped_commit` bind the resulting `session` to
thread `session["user_id"]` through as `imported_by_user_id` — matching
legacy's `auth.current_user(request)["user_id"]` at both of its own
commit call sites (`app/main.py`'s `import_csv`/`import_mapped_commit`).
`import_mapped_preview` needs the CSRF check too (legacy's own version
calls `require_csrf` before it ever reads the upload) but never touched
attribution — it writes nothing — so it only gains `require_csrf_header`
as a bare `dependencies=[...]` entry, not a bound parameter. No target-
scenario picker payload on `GET /import` either — `modules/reference/`
(Phase 1.9) concern, same as every prior module.

**The mapped importer's preview/commit round-trip is JSON-shaped, not
legacy's hidden-form-fields-plus-base64 shape** — `GET /import/mapped`
itself doesn't exist here at all (legacy's own route renders nothing
this module owns: an empty page whose only content is the scenario
picker, a `modules/reference/` concern). `POST /import/mapped/preview`
takes the same multipart upload legacy's did and returns the parsed
picker lists *plus* the file's own content, base64-encoded
(`service.encode_for_roundtrip`) — the frontend holds that in memory and
sends it back verbatim as `schemas.MappedImportCommitRequest.file_
content_b64` when the user confirms the mapping. See `schemas.py`'s own
docstring for why this is a wire-format change, not a behavior one."""
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


@router.post("/mapped/preview", dependencies=[Depends(require_csrf_header)])
async def import_mapped_preview(target_scenario_id: int = Form(...), file: UploadFile = File(...)) -> dict:
    """No `conn`/database at all — parsing and grouping the file's own
    Account/Category values is pure, ported straight from `service.
    preview_mapped`. `target_scenario_id`/`filename` are handed back
    unchanged alongside `file_content_b64` purely so the frontend can
    carry them forward into the commit step without holding separate
    state of its own — same round-trip legacy's hidden form fields
    performed."""
    raw = await file.read()
    try:
        content = service.decode_upload(raw)
        preview = service.preview_mapped(content)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {
        **preview,
        "filename": file.filename or "import.csv",
        "target_scenario_id": target_scenario_id,
        "file_content_b64": service.encode_for_roundtrip(raw),
    }


@router.post("/mapped")
def import_mapped_commit(payload: schemas.MappedImportCommitRequest,
                          session: dict = Depends(require_csrf_header),
                          conn: Connection = Depends(get_connection)) -> dict:
    try:
        content = service.decode_roundtrip(payload.file_content_b64)
        result = service.import_mapped(
            conn, content=content, filename=payload.filename,
            target_scenario_id=payload.target_scenario_id, account_map=payload.account_map,
            category_map=payload.category_map, flip_sign=payload.flip_sign,
            user_id=session["user_id"])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(400, detail=pg_message(e))
    return result
