// The one `openapi-fetch` client every screen imports, instead of each
// screen hand-rolling its own `fetch('/entries?...')` — REBUILD_STATUS.md
// Phase 2.2. `paths` (from `./schema.ts`, generated — see this directory's
// own README) is what makes every call here typo-checked against the
// backend's actual routes and Pydantic request bodies at compile time: a
// path that doesn't exist, or a body missing a required field, is now a
// TypeScript error instead of a 404/422 discovered by clicking around.
//
// `baseUrl` is left at the default (same-origin) on purpose: in dev,
// `vite.config.ts`'s own `server.proxy` makes `/entries` etc. same-origin
// from the browser's point of view already; in prod, FastAPI serves both
// the SPA and the API from the one process Phase 2.1 wired up. There is no
// deployment shape where this client needs to know a different host.
//
// What this deliberately does *not* do yet: attach `X-CSRF-Token` to write
// requests (`modules/auth/deps.py`'s `require_csrf_header`). That needs
// somewhere to *read* the current session's token from, and there is no
// session/auth state anywhere in the frontend yet — the same "don't reach
// into a module that doesn't exist yet" call `modules/reference/router.py`
// documents on the backend side. `use()` below is `openapi-fetch`'s own
// middleware hook, the obvious place to add that once Phase 3's login
// screen gives it a token to read.
import createClient from 'openapi-fetch'

import type { paths } from './schema'

const client = createClient<paths>()

export default client
