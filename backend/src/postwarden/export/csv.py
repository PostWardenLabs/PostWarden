"""CSV export wrapper — ported from `app/main.py`'s `csv_response`,
unchanged."""
import io

from fastapi import Response


def csv_response(buf: io.StringIO, filename: str) -> Response:
    """Wrap a finished `csv.writer` buffer as a download. Excel — still
    the most likely destination for these files — assumes the system
    codepage for a UTF-8 file with no signature, so any accented name or
    currency symbol comes back as mojibake; a leading BOM is what tells
    it the file is actually UTF-8. `modules/imports/`'s own CSV reader
    already decodes with `utf-8-sig`, so a round-tripped export reads
    back in fine."""
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})
