import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { SessionProvider } from './auth/SessionProvider'
import { ConfirmProvider } from './widgets/ConfirmDialog'

// All three mounted once, at the true root — above Shell, not inside it,
// since none is specific to the authenticated chrome: SessionProvider is
// what App.tsx reads to decide whether Shell renders at all (Phase 3.1),
// a confirm dialog is a cross-cutting concern independent of it (Shell
// doesn't render pre-login, but a destructive action could in principle
// need confirming from any screen), and BrowserRouter (new, Phase 3.2)
// has to sit above App.tsx's own `useLocation()` call regardless of
// session state — see App.tsx's own comment on why that's harmless
// during the anonymous/loading branches too. Order between the three
// doesn't matter — none reads from either of the others.
//
// Real browser History API routing (`BrowserRouter`), not hash-based —
// `main.py`'s new `/app`/`/app/{path:path}` fallback routes (Phase 3.2)
// are what make a direct navigation or refresh at a real path like
// `/app/tags` actually work; a hash router would have sidestepped that
// problem instead of solving it, and every path this SPA will ever
// need doubles as `db/seed_demo.sql`-verifiable, bookmarkable, real URL.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <ConfirmProvider>
          <App />
        </ConfirmProvider>
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
)
