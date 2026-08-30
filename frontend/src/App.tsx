import { useEffect, useState } from 'react'

import client from './api/client'
import Shell from './shell/Shell'
import Combobox, { type ComboboxOption } from './widgets/Combobox'
import { useConfirm } from './widgets/confirmContext'
import DatePicker from './widgets/DatePicker'
import NumberStepper from './widgets/NumberStepper'

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

// Stand-in options for the Combobox demo below — real screens (Phase
// 3+) source these from the API (accounts, payees, scenarios, ...) via
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
// Delete once Phase 3's own archetype screens give each widget a real
// caller — see REBUILD_STATUS.md Phase 2.5.
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
      <p>Frontend scaffold (REBUILD_STATUS.md Phase 2.1–2.5).</p>
      <p>Backend: {status}</p>
      <WidgetPreview />
    </Shell>
  )
}

export default App
