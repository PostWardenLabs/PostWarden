import { useState } from 'react'

import { useAppConfig } from './api/useAppConfig'
import { useSession } from './auth/sessionContext'
import LoginPage from './auth/LoginPage'
import Shell from './shell/Shell'
import Combobox, { type ComboboxOption } from './widgets/Combobox'
import { useConfirm } from './widgets/confirmContext'
import DatePicker from './widgets/DatePicker'
import NumberStepper from './widgets/NumberStepper'

// Stand-in options for the Combobox demo below — real screens (Phase
// 3.4+) source these from the API (accounts, payees, scenarios, ...) via
// the typed client, not a hardcoded array.
const PLACEHOLDER_ACCOUNTS: ComboboxOption[] = [
  { value: '1', label: 'Checking' },
  { value: '2', label: 'Savings' },
  { value: '3', label: 'Credit Card' },
]

// Widget preview section for Phase 2.5 — exercises all four ported
// widgets (Combobox, DatePicker, NumberStepper, the confirm dialog via
// useConfirm()) so there's something real for `npm run build` +
// `npm run lint` + a served-bundle content check to verify against.
// Still here after Phase 3.1: login doesn't call any of these (a
// username/password pair and a checkbox need none of them), so none of
// the four gets a real caller until Journal (Phase 3.4) — see
// REBUILD_STATUS.md Phase 2.5's own note on when this section is meant
// to go away.
function WidgetPreview() {
  const [account, setAccount] = useState('')
  const [accounts, setAccounts] = useState(PLACEHOLDER_ACCOUNTS)
  const [date, setDate] = useState('')
  const [amount, setAmount] = useState('0')
  const confirm = useConfirm()
  const [confirmResult, setConfirmResult] = useState<string | null>(null)

  return (
    <section aria-label="Widget preview">
      <h2>Widgets (Phase 2.5)</h2>
      <label className="field">
        Account
        <Combobox
          options={accounts}
          value={account}
          onChange={setAccount}
          onCreate={async (name) => {
            const opt = { value: String(Date.now()), label: name }
            setAccounts((prev) => [...prev, opt])
            return opt
          }}
        />
      </label>
      <label className="field">
        Date
        <DatePicker value={date} onChange={setDate} />
      </label>
      <label className="field">
        Amount
        <NumberStepper value={amount} onChange={setAmount} min="0" max="10" step="1" />
      </label>
      <button
        type="button"
        onClick={async () => {
          const ok = await confirm('Reverse this entry?', { okLabel: 'Reverse' })
          setConfirmResult(ok ? 'confirmed' : 'cancelled')
        }}
      >
        Reverse
      </button>
      {confirmResult && <p>Confirm dialog result: {confirmResult}</p>}
    </section>
  )
}

// Root component. As of Phase 3.1, this is the real end-to-end pipeline
// proof REBUILD_STATUS.md's own checklist wording asked for — not the
// placeholder `GET /healthz` check Phase 2.1/2.2 used instead (removed
// here; a working authenticated session is a strictly stronger signal
// that Vite's build reached FastAPI reached Postgres than a bare
// liveness ping ever was), and not a hardcoded PLACEHOLDER_USER
// (Phase 2.4's own stand-in, also removed).
//
// Three-way branch on `session.status`, matching legacy `auth_gate`'s
// own "redirect to /login, or don't" logic — just without a redirect,
// since `LoginPage` and the authenticated app are both this one
// component tree, not two different server-rendered pages.
function App() {
  const session = useSession()
  const config = useAppConfig()

  if (session.status === 'loading') {
    // The one real gap a server-rendered app never had: `GET /me`'s own
    // round trip, between mount and knowing which of the two branches
    // below applies. Brief in practice (same-origin, no real network
    // hop in dev or prod) and intentionally minimal here — no spinner
    // widget exists yet, and one bare loading state isn't reason enough
    // to build one.
    return <p>Loading…</p>
  }

  if (session.status === 'anonymous') {
    return <LoginPage />
  }

  return (
    <Shell title="Dashboard" current="dashboard" user={session.user} onLogout={session.logout}
           version={config.version || undefined}>
      <h1>PostWarden</h1>
      <p>Frontend scaffold (REBUILD_STATUS.md Phase 2.1–3.1).</p>
      <WidgetPreview />
    </Shell>
  )
}

export default App
