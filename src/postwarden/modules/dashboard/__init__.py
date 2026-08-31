"""The Dashboard landing page's backend. Phase 4.7 — the one module in
this rebuild whose backend didn't exist before this phase: every other
module here was ported during Phase 1 (see REBUILD.md's own phase
table) and Phase 4 has been frontend-only ever since. The legacy route
this ports (`app/main.py`'s bare `GET /`) never had a JSON shape at all,
so there was nothing for an earlier phase to have already done.
"""
