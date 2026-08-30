import { useEffect, useState } from 'react'

// Placeholder root component — Phase 2.1's own scope is the build/serve
// pipeline, not the app shell (that's REBUILD_STATUS.md's Phase 2.4). The
// live /healthz check exists to prove the pipeline end to end (Vite build
// -> FastAPI StaticFiles -> a real fetch reaching the real backend), the
// same reason Phase 0's own main.py shipped a trivial /healthz route before
// anything else did.
type BackendStatus = 'checking' | 'ok' | 'unreachable'

function App() {
  const [status, setStatus] = useState<BackendStatus>('checking')

  useEffect(() => {
    fetch('/healthz')
      .then((res) => (res.ok ? setStatus('ok') : setStatus('unreachable')))
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
