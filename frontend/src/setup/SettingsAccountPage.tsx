import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useSession } from '../auth/sessionContext'

// Ported from app/templates/account.html (Phase 4.2) — the "Manage
// account" destination `SettingsPage.tsx`'s own Account panel links to,
// same split legacy already had (`/settings` is the hub, `/settings/
// account` is this form). Backend routes already existed before this
// phase touched anything (`modules/auth/router.py`'s `POST /settings/
// username`/`POST /settings/password`, mounted since Phase 1.14).
//
// One real, medium-dictated difference on the password form: legacy
// redirects to `/login?ok=Password+changed...` after
// `delete_all_sessions_for_user` — a real page navigation, so the flash
// survives in the URL. `LoginPage.tsx` has no equivalent yet (see its
// own file comment: "nothing in the SPA redirects to a login screen on
// success today"), and adding one is out of scope for this screen alone.
// Shown inline here instead, then `session.logout()` (which clears local
// session state and drops this component in favor of `LoginPage`) fires
// after a short delay — long enough to actually read the confirmation
// before being signed out, not so long it feels stuck. The session is
// already dead server-side the moment `POST /settings/password` returns
// 200 (`change_password`'s own `delete_all_sessions_for_user` runs before
// responding), so nothing is lost by the delay — any other request in
// that window would already 401 on its own via `client.ts`'s global
// unauthorized handler.
interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

export default function SettingsAccountPage() {
  const session = useSession()

  const [username, setUsername] = useState(session.user?.username ?? '')
  const [usernameFlash, setUsernameFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [savingUsername, setSavingUsername] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordFlash, setPasswordFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [changingPassword, setChangingPassword] = useState(false)

  async function submitUsername(e: FormEvent) {
    e.preventDefault()
    setSavingUsername(true)
    setUsernameFlash(null)
    const { data, error } = await client.POST('/settings/username', { body: { username } })
    setSavingUsername(false)
    if (error) {
      setUsernameFlash({ err: errorDetail(error, 'Could not change username') })
      return
    }
    const saved = (data as unknown as { username: string }).username
    setUsername(saved)
    session.setUsername(saved)
    setUsernameFlash({ ok: `Username changed to “${saved}”` })
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault()
    setChangingPassword(true)
    setPasswordFlash(null)
    const { error } = await client.POST('/settings/password', {
      body: { current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword },
    })
    setChangingPassword(false)
    if (error) {
      setPasswordFlash({ err: errorDetail(error, 'Could not change password') })
      return
    }
    setPasswordFlash({ ok: 'Password changed — signing you out…' })
    setTimeout(() => {
      void session.logout()
    }, 1500)
  }

  return (
    <>
      <p className="page-sub">
        <Link className="quiet-link" to="/app/settings">
          &larr; Back to Settings
        </Link>
      </p>

      <div className="panel">
        <h2>Change username</h2>
        {usernameFlash?.ok && <div className="flash flash-ok">{usernameFlash.ok}</div>}
        {usernameFlash?.err && <div className="flash flash-err">{usernameFlash.err}</div>}
        <form className="grid-form" onSubmit={submitUsername}>
          <label className="field">
            Username
            <input
              type="text"
              required
              // The hyphen must be escaped — current Chrome compiles a
              // `pattern` attribute in unicode-sets (`v`-flag) mode,
              // where a trailing `-` in a character class is no longer
              // auto-literal the way plain-regex mode always treated
              // it. Unescaped, this throws "Invalid character in
              // character class" in the console and the native pattern
              // check silently stops validating anything (caught in
              // Phase 4.2's own manual verification, not by any type
              // check — TypeScript sees a plain string). Same backend
              // constraint either way: `modules/auth/schemas.py`'s own
              // `ChangeUsernameRequest` still owns the real validation.
              pattern="[a-z0-9_.\-]{3,32}"
              title="3-32 characters: lowercase letters, numbers, _ . or -"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <button type="submit" disabled={savingUsername}>
            Save username
          </button>
        </form>
      </div>

      <div className="panel">
        <h2>Change password</h2>
        {passwordFlash?.ok && <div className="flash flash-ok">{passwordFlash.ok}</div>}
        {passwordFlash?.err && <div className="flash flash-err">{passwordFlash.err}</div>}
        <form className="grid-form" onSubmit={submitPassword}>
          <label className="field">
            Current password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </label>
          <label className="field">
            New password
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="field">
            Confirm new password
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </label>
          <button type="submit" disabled={changingPassword}>
            Change password
          </button>
        </form>
        <p className="dim small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          Changing your password signs you out everywhere, including here — you'll need to log
          back in with the new one.
        </p>
      </div>
    </>
  )
}
