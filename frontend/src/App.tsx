import { useState } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'

import { useAppConfig } from './api/useAppConfig'
import { useSession } from './auth/sessionContext'
import LoginPage from './auth/LoginPage'
import JournalPage from './journal/JournalPage'
import BalanceSheetPage from './reports/BalanceSheetPage'
import CashFlowPage from './reports/CashFlowPage'
import IncomeStatementPage from './reports/IncomeStatementPage'
import LedgerPage from './reports/LedgerPage'
import TrialBalancePage from './reports/TrialBalancePage'
import VariancePage from './reports/VariancePage'
import PayeesPage from './setup/PayeesPage'
import ScenariosPage from './setup/ScenariosPage'
import Shell from './shell/Shell'
import TagsPage from './tags/TagsPage'
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

// Everything the placeholder root route ("/") has shown since Phase 2.1 —
// unchanged in substance by Phase 3.2's routing, just moved into its own
// component now that "/" is one of (currently) two real routes rather
// than the only thing App ever rendered.
function Dashboard() {
  return (
    <>
      <h1>PostWarden</h1>
      <p>Frontend scaffold (REBUILD_STATUS.md Phase 2.1–3.2).</p>
      <WidgetPreview />
    </>
  )
}

// Maps a real browser path to the `current` key Sidebar.tsx/Topbar.tsx
// use for active-link highlighting — deliberately a plain if-chain, not a
// lookup shared with nav.ts's own NAV_GROUPS: only two paths are real
// routes right now, and a link's own `key` (nav.ts) already has to match
// this independently since neither file imports from the other. Grows by
// one line per screen as Phase 4 moves each into `/app/*`, same as
// nav.ts's own `client` flag.
function routeKey(pathname: string): string {
  if (pathname === '/app/tags') return 'tags'
  if (pathname === '/app/payees') return 'payees'
  if (pathname === '/app/scenarios') return 'scenarios'
  if (pathname === '/app/trial-balance') return 'tb'
  if (pathname === '/app/entries') return 'entries'
  if (pathname === '/app/balance-sheet') return 'balance_sheet'
  if (pathname === '/app/cash-flow') return 'cash_flow'
  if (pathname === '/app/income-statement') return 'income_statement'
  if (pathname === '/app/variance') return 'variance'
  if (pathname === '/app/ledger') return 'ledger'
  return 'dashboard'
}

// Shell's own topbar title, one entry per real route — a plain object
// keyed the same way `routeKey` above returns, replacing what was a
// two-way ternary (Phase 3.2) now that a third screen exists. Same
// `nav.ts`-independent duplication `routeKey` already accepts (see its
// own comment) rather than importing NAV_GROUPS' own labels, which
// aren't keyed for a 1:1 lookup this cheap anyway.
const PAGE_TITLES: Record<string, string> = {
  tags: 'Tags',
  payees: 'Payees',
  scenarios: 'Scenarios',
  tb: 'Trial Balance',
  entries: 'Journal',
  balance_sheet: 'Balance Sheet',
  cash_flow: 'Cash Flow',
  income_statement: 'Income Statement',
  variance: 'Variance',
  ledger: 'Ledger',
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
//
// As of Phase 3.2, the authenticated branch also renders a real
// `<Routes>` — Tags is the first screen with its own URL (`/app/tags`,
// not the bare `/tags` GET /tags itself already owns; see main.py's own
// comment on why `/app`, not `/api`). `useLocation()` needs a `<Router>`
// ancestor, mounted once in main.tsx above everything, including the
// anonymous/loading branches below — harmless there since neither of
// those renders anything location-dependent, and it means `<Router>`
// doesn't have to be conditionally mounted/unmounted across a login.
function App() {
  const session = useSession()
  const config = useAppConfig()
  const location = useLocation()

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

  const current = routeKey(location.pathname)

  return (
    <Shell title={PAGE_TITLES[current] ?? 'Dashboard'} current={current}
           user={session.user} onLogout={session.logout} version={config.version || undefined}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/app/tags" element={<TagsPage />} />
        <Route path="/app/payees" element={<PayeesPage />} />
        <Route path="/app/scenarios" element={<ScenariosPage />} />
        <Route path="/app/trial-balance" element={<TrialBalancePage />} />
        <Route path="/app/balance-sheet" element={<BalanceSheetPage />} />
        <Route path="/app/cash-flow" element={<CashFlowPage />} />
        <Route path="/app/income-statement" element={<IncomeStatementPage />} />
        <Route path="/app/variance" element={<VariancePage />} />
        <Route path="/app/ledger" element={<LedgerPage />} />
        <Route path="/app/entries" element={<JournalPage />} />
      </Routes>
    </Shell>
  )
}

export default App
