import { useEffect, useState } from 'react'

import client from './api/client'
import Shell from './shell/Shell'

// Placeholder root component — Phase 2.1/2.2's own scope was the build/
// serve pipeline and the typed client; Phase 2.4 added the shell around
// it (Shell.tsx). The live /healthz check exists to prove the pipeline
// end to end (Vite build -> FastAPI StaticFiles -> a real typed request
// reaching the real backend), the same reason Phase 0's own main.py
// shipped a trivial /healthz route before anything else did. Goes
// through `client.GET(...)` rather than a bare `fetch('/healthz')` as of
// Phase 2.2, specifically so this doubles as this repo's own proof the
// generated client actually works, not just that it compiles.
type BackendStatus = 'checking' | 'ok' | 'unreachable'

// A stand-in session, purely so this phase's own shell (sidebar, topbar
// user area) has something to render and be verified against — there is
// no real session anywhere in the frontend yet. Delete once Phase 3.1
// (login) provides the genuine article; nothing else in Shell.tsx/
// Topbar.tsx/Sidebar.tsx should need to change when that happens, since
// they already take `user` as a plain nullable prop.
const PLACEHOLDER_USER = { username: 'david' }

function App() {
  const [status, setStatus] = useState<BackendStatus>('checking')

  useEffect(() => {
    client
      .GET('/healthz')
      .then(({ error }) => setStatus(error ? 'unreachable' : 'ok'))
      .catch(() => setStatus('unreachable'))
  }, [])

  return (
    <Shell title="Dashboard" current="dashboard" user={PLACEHOLDER_USER}>
      <h1>PostWarden</h1>
      <p>Frontend scaffold (REBUILD_STATUS.md Phase 2.1–2.4).</p>
      <p>Backend: {status}</p>
    </Shell>
  )
}

export default App
