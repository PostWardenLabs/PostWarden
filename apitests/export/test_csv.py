"""Unit tests for `export.csv` — no database, no framework beyond the
`Response` object itself."""
import io

from postwarden.export.csv import csv_response


def test_csv_response_prefixes_a_bom_and_sets_content_type():
    buf = io.StringIO()
    buf.write("a,b\n1,2\n")
    resp = csv_response(buf, "report.csv")
    assert resp.media_type == "text/csv; charset=utf-8"
    assert resp.headers["content-disposition"] == 'attachment; filename="report.csv"'
    assert resp.body.decode("utf-8-sig") == "a,b\n1,2\n"
    # The BOM itself really is there, not just invisible in the decoded
    # string above — the whole reason csv_response exists.
    assert resp.body.startswith(b"\xef\xbb\xbf")
