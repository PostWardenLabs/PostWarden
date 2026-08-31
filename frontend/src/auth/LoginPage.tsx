import { useEffect, useRef, useState, type FormEvent } from 'react'

import { useAppConfig } from '../api/useAppConfig'
import { useSession } from './sessionContext'

// The one screen in the app that skips the normal topbar/sidebar shell
// entirely for a full-page split: brand on the left, the form (plus the
// demo callout, when applicable) on the right. See index.css's own
// header comment for the .auth-*/.demo-callout/.checkline/.grid-form
// rules this renders against.
//
// A failed login sets local `error` state directly from `session.login()`'s
// return value — no query-string flash or redirect involved, since this
// component stays mounted through the attempt. Demo credentials and the
// app version come from `GET /config` (`useAppConfig`).
export default function LoginPage() {
  const session = useSession()
  const config = useAppConfig()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The demo callout's own credentials only exist once `GET /config`
  // resolves, one tick after this component's first render — seeded
  // here, exactly once (the `seededDemo` ref, not a value-is-still-
  // empty check), the moment `config` actually reports a demo instance.
  // Once-only matters: a plain "seed while the field reads empty" guard
  // would also fire every time a user *cleared* the field by hand after
  // config had already loaded, silently refilling it and making the
  // field impossible to actually clear.
  const seededDemo = useRef(false)
  useEffect(() => {
    if (seededDemo.current || !config.demo_user) return
    seededDemo.current = true
    setUsername(config.demo_user)
    setPassword(config.demo_password ?? '')
  }, [config.demo_user, config.demo_password])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    const result = await session.login(username, password, remember)
    setSubmitting(false)
    if (!result.ok) setError(result.error)
  }

  return (
    <div className="auth-split">
      <div className="auth-brand">
        <span className="auth-wordmark">PostWarden</span>
        {config.version && <span className="auth-version">v{config.version}</span>}
      </div>
      <div className="auth-panel">
        <div className="auth-form-wrap">
          <h2>Log in</h2>
          {error && <div className="flash flash-err">{error}</div>}
          <form className="grid-form" style={{ gridTemplateColumns: '1fr' }} onSubmit={handleSubmit}>
            <label className="field">
              Username
              <input
                type="text"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                autoComplete="username"
              />
            </label>
            <label className="field">
              Password
              <input
                type="password"
                name="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </label>
            <label className="checkline">
              <input
                type="checkbox"
                name="remember"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              Remember me
            </label>
            <button type="submit" disabled={submitting}>
              Log in
            </button>
          </form>
        </div>
        {config.demo_banner && (
          <div className="demo-callout">
            <p>
              User: <code className="mono"><strong>{config.demo_user}</strong></code>
            </p>
            <p>
              Password: <code className="mono"><strong>{config.demo_password}</strong></code>
            </p>
            <p>credentials prefilled in</p>
          </div>
        )}
      </div>
    </div>
  )
}
