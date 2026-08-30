"""Session auth — login/logout, the session-cookie mechanism every other
write module's own docstring points back to, and the account settings
screen (username/password). Phase 1.11.

Ported from `app/auth.py` + the "Auth"/"User settings" sections of
`app/main.py`. Same design as legacy, carried over deliberately rather
than replaced with something more fashionable (a JWT, say): a session is
a random opaque token stored in `sessions` (`db/schema.sql`), looked up
on every request — no signing secret to manage, and logout is a plain
`DELETE`. REBUILD.md decision 4 is "port behavior, don't redesign it
along the way" outside the golden-master question, and nothing about
moving to a JSON API changes the tradeoffs that made this the right
shape for a single-user, cookie-same-origin deployment in the first
place.

**Scope of this phase, and what it deliberately leaves for Phase
1.14.** This module builds the *mechanism* — `service.login`/`logout`/
`get_session`, `deps.get_current_session`/`require_csrf` as reusable
FastAPI dependencies, the account-settings routes — and proves all of it
end to end against a real Postgres. It does **not** retrofit
`modules/entries/`, `/staging/`, `/imports/`, `/budget/`, `/reference/`,
or `/scheduling/` to actually call `deps.get_current_session`/
`require_csrf`, even though several of those modules' own docstrings
name this phase as the one that closes their "no CSRF check, no
attribution" gap. Two things settle that in favor of deferring the
retrofit rather than doing it here:

1. **Precedent already set by this same rebuild.** `modules/budget/
   service.py`'s own Phase 1.7 docstring flags "no default-scenario
   selection, since `modules/reference/` doesn't exist yet" — and Phase
   1.9, the phase that actually built `modules/reference/`, did not go
   back and wire that default in. A module documenting "closeable once X
   exists" has consistently meant *the mechanism becomes available*, not
   *X's own phase must immediately retrofit every caller* — that
   retrofit happens once, at real integration time, alongside whatever
   else assembling the app for real requires.
2. **Phase 1.14 ("`main.py` cut down to app factory + router mounting
   only") is explicitly where every module's router gets mounted
   together for the first time.** Auth is the one dependency every
   write route across every module needs identically — wiring it in
   makes far more sense done once, at the point all routers are already
   being touched to be mounted, than scattered as five separate
   half-done retrofits ahead of that, each needing its own set of
   fixture/test changes to a module this phase has no other reason to
   touch.

This is also the one place in the rebuild so far where a module
genuinely *should* be imported directly by its future callers, not
forked — see `deps.py`'s own docstring for why that doesn't conflict
with REBUILD.md decision 3's "a module should be deletable on its own"
test.
"""
