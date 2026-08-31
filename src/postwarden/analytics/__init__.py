"""Star-schema views + the documented `/api/*` contract (5 routes:
trial-balance, accounts, scenarios, entries, monthly-activity), plus the
Connect BI settings routes that describe the same star schema to a human
(`service.py`'s own docstring explains why the latter live here). Reads
only; no writes, no CSRF.
"""
