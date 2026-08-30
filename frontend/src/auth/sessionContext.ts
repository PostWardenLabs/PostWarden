import { createContext, useContext } from 'react'

export interface SessionUser {
  id: number
  username: string
}

export type LoginResult = { ok: true } | { ok: false; error: string }

export interface SessionValue {
  // 'loading' only ever covers the very first GET /me on mount — every
  // transition after that (login/logout/a stale-cookie 401) goes
  // straight between 'authenticated' and 'anonymous', so a screen
  // never sees a second loading flicker once the app has decided once.
  status: 'loading' | 'authenticated' | 'anonymous'
  user: SessionUser | null
  login: (username: string, password: string, remember: boolean) => Promise<LoginResult>
  logout: () => Promise<void>
  // Updates the in-memory session's username without a round trip to
  // GET /me — SettingsAccountPage.tsx's own submitUsername already has
  // the new value from a successful POST /settings/username response;
  // without this, every other reader of `user.username` (Topbar's own
  // username link, this same screen's "Signed in as" line on
  // SettingsPage) stayed stale until the next full page load, since
  // nothing previously wrote a rename back into this context — caught
  // in Phase 4.2's own manual verification pass, not by any type check.
  setUsername: (username: string) => void
}

// Split out of SessionProvider.tsx for the same reason confirmContext.ts
// is split from ConfirmDialog.tsx — oxlint's react(only-export-
// components) flags a component file that also exports a plain hook/
// context as a Fast Refresh hazard.
export const SessionContext = createContext<SessionValue | null>(null)

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession() must be used inside <SessionProvider>')
  return ctx
}
