import { useCallback, useEffect, useState, type ReactNode } from 'react'

import client, { setCsrfToken, setUnauthorizedHandler } from '../api/client'
import { SessionContext, type SessionUser, type SessionValue } from './sessionContext'

// The real session state Phase 2.4's own Shell.tsx/App.tsx left as a
// hardcoded PLACEHOLDER_USER, and the real `onLogout` Topbar.tsx's own
// comment described as "where Phase 3.1 wires a real client.POST(
// '/logout', ...) call instead."
//
// `/login`, `/logout`, and `/me` all answer with a bare Pydantic-free
// `dict` (see modules/auth/router.py's own module docstring: "response
// shapes stay plain dicts, only request bodies get a model") — FastAPI's
// OpenAPI generation has no field-level schema to offer for those, so
// openapi-typescript types every one of these responses as
// `{[key: string]: unknown}`. The local interfaces below (`LoginBody`/
// `MeBody`) describe the actual, real shape each route's own docstring
// promises, and every read of `data` below is cast through one of them —
// the same kind of gap `client.ts`'s own file comment already flags for
// `X-CSRF-Token`, just realized here instead of stayed a comment.
interface LoginBody {
  id: number
  username: string
  csrf_token: string
}
// Same shape /login's own response has (see LoginBody above) — router.py's
// own docstring on GET /me spells out why: it deliberately echoes the
// same id/username/csrf_token triple, not a coincidence worth a second
// independent type.
type MeBody = LoginBody
interface ErrorBody {
  detail?: string
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionValue['status']>('loading')
  const [user, setUser] = useState<SessionUser | null>(null)

  function becomeAuthenticated(body: LoginBody) {
    setCsrfToken(body.csrf_token)
    setUser({ id: body.id, username: body.username })
    setStatus('authenticated')
  }

  function becomeAnonymous() {
    setCsrfToken(null)
    setUser(null)
    setStatus('anonymous')
  }

  // The one GET /me on mount — the SPA's own equivalent of legacy
  // `auth_gate` reading the session cookie on every server-rendered
  // page load, just run once here instead of per navigation, since
  // there's no client-side router re-mounting this component on one
  // (REBUILD_STATUS.md Phase 2.4's own note on why Sidebar's links are
  // still plain <a href>s).
  useEffect(() => {
    let cancelled = false
    client.GET('/me').then(({ data, error }) => {
      if (cancelled) return
      if (error || !data) becomeAnonymous()
      else becomeAuthenticated(data as unknown as MeBody)
    })
    return () => {
      cancelled = true
    }
  }, [])

  // Registered once, for the lifetime of this provider — see client.ts's
  // own comment on why a 401 from *any* screen's request needs to reach
  // here, not just this file's own /login-time failure handling.
  useEffect(() => {
    setUnauthorizedHandler(becomeAnonymous)
    return () => setUnauthorizedHandler(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = useCallback<SessionValue['login']>(async (username, password, remember) => {
    const { data, error } = await client.POST('/login', {
      body: { username, password, remember },
    })
    if (error || !data) {
      const detail = (error as ErrorBody | undefined)?.detail
      return { ok: false, error: detail || 'Invalid username or password' }
    }
    becomeAuthenticated(data as unknown as LoginBody)
    return { ok: true }
  }, [])

  const logout = useCallback(async () => {
    // Same forgiving shape router.py's own /logout has: no CSRF check,
    // and this clears local state regardless of whether the request
    // itself even reaches the server — "worst case is a no-op logout"
    // extends naturally to "worst case is a client that thinks it's
    // logged out one round trip early."
    await client.POST('/logout')
    becomeAnonymous()
  }, [])

  const value: SessionValue = { status, user, login, logout }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
