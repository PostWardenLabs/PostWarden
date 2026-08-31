import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { SessionProvider } from './auth/SessionProvider'
import { initCentsEntry } from './format/centsEntry'
import { ConfirmProvider } from './widgets/ConfirmDialog'

// Global, not a React concern — same reasoning `centsEntry.ts`'s own
// file comment gives: a `document`-level delegated listener that needs
// to exist exactly once, independent of which screen or which entry
// grid is currently mounted, mirroring index.html's own pre-paint
// theme/font script sitting outside the React tree entirely.
initCentsEntry()

// All three mounted once, at the true root — above Shell, not inside it,
// since none is specific to the authenticated chrome: SessionProvider is
// what App.tsx reads to decide whether Shell renders at all, a confirm
// dialog is a cross-cutting concern independent of it (Shell doesn't
// render pre-login, but a destructive action could in principle need
// confirming from any screen), and BrowserRouter has to sit above
// App.tsx's own `useLocation()` call regardless of session state — see
// App.tsx's own comment on why that's harmless during the anonymous/
// loading branches too. Order between the three doesn't matter — none
// reads from either of the others.
//
// Real browser History API routing (`BrowserRouter`), not hash-based —
// `main.py`'s `/app`/`/app/{path:path}` fallback routes are what make a
// direct navigation or refresh at a real path like `/app/tags` actually
// work; a hash router would have sidestepped that problem instead of
// solving it, and every path this SPA will ever need doubles as
// `db/seed_demo.sql`-verifiable, bookmarkable, real URL.
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
