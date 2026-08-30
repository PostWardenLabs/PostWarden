import { useEffect, useState } from 'react'

import client from './api/client'

// Placeholder root component — Phase 2.1/2.2's own scope is the build/
// serve pipeline and the typed client, not the app shell (that's
// REBUILD_STATUS.md's Phase 2.4). The live /healthz check exists to prove
// the pipeline end to end (Vite build -> FastAPI StaticFiles -> a real
// typed request reaching the real backend), the same reason Phase 0's own
// main.py shipped a trivial /healthz route before anything else did. Goes
// through `client.GET(...)` rather than a bare `fetch('/healthz')` as of
// Phase 2.2, specifically so this doubles as this repo's own proof the
// generated client actually works, not just that it compiles.
type BackendStatus = 'checking' | 'ok' | 'unreachable'

function App() {
  const [status, setStatus] = useState<BackendStatus>('checking')

  useEffect(() => {
    client
      .GET('/healthz')
      .then(({ error }) => setStatus(error ? 'unreachable' : 'ok'))
      .catch(() => setStatus('unreachable'))
  }, [])

  return (
    <main>
      <h1>PostWarden</h1>
      <p>Frontend scaffold (REBUILD_STATUS.md Phase 2.1).</p>
      <p>Backend: {status}</p>
    </main>
  )
}

export default App
