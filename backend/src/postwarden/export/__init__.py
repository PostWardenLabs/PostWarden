"""Shared CSV/XLSX writers, consumed by `modules/entries/` and
`modules/reports/` alike (`modules/imports/` reads CSV, it never writes
one, so it has no reason to depend on this package).

Two files, ported from `app/main.py`'s module-level export plumbing
(the ~260 lines that sat just above the Auth section, shared by every
`/export/*` route that came after them):

- `csv.py` — `csv_response()`, the BOM-prefixed `text/csv` wrapper every
  CSV export returns through.
- `xlsx.py` — the openpyxl style palette (fonts, fills, borders, number
  formats) and the row/header/formula helpers built on top of it, plus
  `xlsx_response()`, the XLSX counterpart to `csv_response()`.

Both are pure formatting: a caller hands them already-computed rows
(from `modules/reports/service.py` or `modules/entries/service.py`) and
gets a `fastapi.Response` back. Neither file ever touches a database —
that's what makes this package safe for both consuming modules to
depend on without breaking REBUILD.md decision 3's "deletable on its
own" test for either of *them* (this package has no business logic of
its own to delete anything out from under).

XLSX output carries live Excel formulas (cell-by-cell sums and
variance/% variance pairs, never a row range) rather than baked-in
figures — see `xlsx.py`'s own docstring on `xlsx_sum_formula`/
`xlsx_variance_formulas` for why a range would silently double-count a
rolled-up multi-level account tree.
"""
