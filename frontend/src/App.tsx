import { Route, Routes, useLocation } from 'react-router-dom'

import { useAppConfig } from './api/useAppConfig'
import { useSession } from './auth/sessionContext'
import LoginPage from './auth/LoginPage'
import BudgetPage from './budget/BudgetPage'
import JournalPage from './journal/JournalPage'
import BalanceSheetPage from './reports/BalanceSheetPage'
import CashFlowPage from './reports/CashFlowPage'
import DashboardPage from './reports/DashboardPage'
import IncomeStatementPage from './reports/IncomeStatementPage'
import LedgerPage from './reports/LedgerPage'
import TrialBalancePage from './reports/TrialBalancePage'
import VariancePage from './reports/VariancePage'
import AccountLevelsPage from './setup/AccountLevelsPage'
import AccountsPage from './setup/AccountsPage'
import EntryTemplatesPage from './setup/EntryTemplatesPage'
import PayeesPage from './setup/PayeesPage'
import ScenariosPage from './setup/ScenariosPage'
import ScheduledPage from './setup/ScheduledPage'
import SettingsAccountPage from './setup/SettingsAccountPage'
import SettingsPage from './setup/SettingsPage'
import Shell from './shell/Shell'
import StagingDuplicatesPage from './staging/StagingDuplicatesPage'
import StagingPage from './staging/StagingPage'
import TagsPage from './tags/TagsPage'

// Maps a real browser path to the `current` key Sidebar.tsx/Topbar.tsx
// use for active-link highlighting — deliberately a plain if-chain, not a
// lookup shared with nav.ts's own NAV_GROUPS: only two paths are real
// routes right now, and a link's own `key` (nav.ts) already has to match
// this independently since neither file imports from the other. Grows by
// one line per screen as Phase 4 moves each into `/app/*`, same as
// nav.ts's own `client` flag.
function routeKey(pathname: string): string {
  if (pathname === '/app/accounts') return 'accounts'
  if (pathname === '/app/tags') return 'tags'
  if (pathname === '/app/payees') return 'payees'
  if (pathname === '/app/scenarios') return 'scenarios'
  if (pathname === '/app/account-levels') return 'account_levels'
  if (pathname === '/app/scheduled') return 'scheduled'
  if (pathname === '/app/templates') return 'templates'
  if (pathname === '/app/settings/account') return 'settings_account'
  if (pathname === '/app/settings') return 'settings'
  if (pathname === '/app/trial-balance') return 'tb'
  if (pathname === '/app/entries') return 'entries'
  if (pathname === '/app/staging') return 'staging'
  if (pathname === '/app/staging/duplicates') return 'staging_duplicates'
  if (pathname === '/app/budget') return 'budget'
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
  accounts: 'Accounts',
  tags: 'Tags',
  payees: 'Payees',
  scenarios: 'Scenarios',
  account_levels: 'Account levels',
  scheduled: 'Scheduled Entries',
  templates: 'Templates',
  settings: 'Settings',
  settings_account: 'Account',
  tb: 'Trial Balance',
  entries: 'Journal',
  staging: 'Staging',
  staging_duplicates: 'Find Duplicates',
  budget: 'Budget Grid',
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
        <Route path="/" element={<DashboardPage />} />
        <Route path="/app/accounts" element={<AccountsPage />} />
        <Route path="/app/tags" element={<TagsPage />} />
        <Route path="/app/payees" element={<PayeesPage />} />
        <Route path="/app/scenarios" element={<ScenariosPage />} />
        <Route path="/app/account-levels" element={<AccountLevelsPage />} />
        <Route path="/app/scheduled" element={<ScheduledPage />} />
        <Route path="/app/templates" element={<EntryTemplatesPage />} />
        <Route path="/app/settings" element={<SettingsPage />} />
        <Route path="/app/settings/account" element={<SettingsAccountPage />} />
        <Route path="/app/trial-balance" element={<TrialBalancePage />} />
        <Route path="/app/balance-sheet" element={<BalanceSheetPage />} />
        <Route path="/app/cash-flow" element={<CashFlowPage />} />
        <Route path="/app/income-statement" element={<IncomeStatementPage />} />
        <Route path="/app/variance" element={<VariancePage />} />
        <Route path="/app/ledger" element={<LedgerPage />} />
        <Route path="/app/entries" element={<JournalPage />} />
        <Route path="/app/staging" element={<StagingPage />} />
        <Route path="/app/staging/duplicates" element={<StagingDuplicatesPage />} />
        <Route path="/app/budget" element={<BudgetPage />} />
      </Routes>
    </Shell>
  )
}

export default App
