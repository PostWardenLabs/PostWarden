import { useEffect, useState } from 'react'

import client from './client'

// GET /config's real shape (main.py's own docstring) — plain-dict
// response, so openapi-typescript can only offer `{[key: string]: unknown}`
// for it, same gap `auth/SessionProvider.tsx`'s own comment documents for
// /login and /me.
export interface AppConfig {
  version: string
  demo_banner: boolean
  demo_user: string | null
  demo_password: string | null
}

const FALLBACK: AppConfig = { version: '', demo_banner: false, demo_user: null, demo_password: null }

// A plain hook, not a Context/Provider — unlike SessionProvider, nothing
// here needs to be written to from outside the component that reads it,
// and LoginPage/Shell.tsx are the only two callers (mutually exclusive in
// practice: one renders while anonymous, the other while authenticated),
// so there's no real state to share between them, just the same one-shot
// GET /config each would otherwise duplicate the fetch logic for.
export function useAppConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(FALLBACK)

  useEffect(() => {
    let cancelled = false
    client.GET('/config').then(({ data }) => {
      if (!cancelled && data) setConfig(data as unknown as AppConfig)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return config
}
