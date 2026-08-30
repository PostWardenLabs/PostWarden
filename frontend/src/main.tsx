import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { SessionProvider } from './auth/SessionProvider'
import { ConfirmProvider } from './widgets/ConfirmDialog'

// Both mounted once, at the true root — above Shell, not inside it,
// since neither is specific to the authenticated chrome: SessionProvider
// is what App.tsx reads to decide whether Shell renders at all (Phase
// 3.1), and a confirm dialog is a cross-cutting concern independent of
// it (Shell doesn't render pre-login, but a destructive action could in
// principle need confirming from any screen). Order between the two
// doesn't matter — neither reads from the other.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SessionProvider>
      <ConfirmProvider>
        <App />
      </ConfirmProvider>
    </SessionProvider>
  </StrictMode>,
)
