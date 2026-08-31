"""Star-schema views + the documented `/api/*` contract (the 5 existing
routes: trial-balance, accounts, scenarios, entries, monthly-activity),
plus the Connect BI settings routes that describe the same star schema
to a human (`service.py`'s own docstring explains why the latter live
here). Phase 1.13 — ported from `app/main.py`'s JSON-API section and its
Settings/connect-bi routes. Reads only; no writes, no CSRF, nothing to
port from `modules/auth/`.
"""
