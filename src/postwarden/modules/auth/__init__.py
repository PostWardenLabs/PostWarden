"""Session auth — login/logout, the session-cookie mechanism every other
write module depends on, and the account settings screen
(username/password).

A session is a random opaque token stored in `sessions`
(`db/schema.sql`), looked up on every request — no signing secret to
manage (a JWT, say), and logout is a plain `DELETE`. This is the right
shape for a single-user, cookie-same-origin deployment; nothing about
being a JSON API changes that.

Every other module's `APIRouter` sets `deps.get_current_session` at its
own router-level `dependencies=[...]`, and every write route
additionally depends on `deps.require_csrf_header` — see `deps.py`'s own
docstring for why this module is imported directly by its callers
rather than forked, unlike sibling business modules.
"""
