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
