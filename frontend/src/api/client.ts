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
// As of Phase 3.1 (login), this also attaches `X-CSRF-Token` to every
// non-GET request (`modules/auth/deps.py`'s `require_csrf_header`) and
// notifies `auth/SessionProvider.tsx` when any response comes back 401 —
// see the two exports below. A plain module-level variable, not React
// state, is the right home for the token itself: this file has no
// component tree of its own to hold state in, and every screen's own
// `client.POST(...)` call needs the *current* token synchronously, not
// a value threaded through props from wherever `SessionProvider` sits.
// `SessionProvider` is the only writer (`setCsrfToken` after a
// successful `/login` or `/me`, `null` after `/logout` or a 401);
// everything else only ever reads through the middleware below.
import createClient from 'openapi-fetch'

import type { paths } from './schema'

const client = createClient<paths>()

let csrfToken: string | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

let onUnauthorized: (() => void) | null = null

// `SessionProvider` registers itself here so a session that expired
// server-side (cookie still present but the row behind it is gone or
// past `SESSION_TTL`) is noticed the moment *any* screen's request
// 401s, not only at the next full page load's own `GET /me` — the
// closest equivalent this SPA has to legacy `auth_gate`'s own redirect-
// to-`/login` on a stale cookie, without a client-side router to
// actually redirect through yet (REBUILD_STATUS.md Phase 2.4's own
// note on why Sidebar/Topbar links are still plain `<a href>`s).
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

client.use({
  onRequest({ request }) {
    if (csrfToken && request.method !== 'GET') {
      request.headers.set('X-CSRF-Token', csrfToken)
    }
    return request
  },
  onResponse({ response }) {
    if (response.status === 401) onUnauthorized?.()
    return response
  },
})

export default client
