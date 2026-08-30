import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ConfirmProvider } from './widgets/ConfirmDialog'

// Mounted once, at the true root — above Shell, not inside it, since a
// confirm dialog is a cross-cutting concern independent of the app
// chrome (Shell doesn't render at all pre-login, but a destructive
// action could in principle need confirming from any screen).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfirmProvider>
      <App />
    </ConfirmProvider>
  </StrictMode>,
)
