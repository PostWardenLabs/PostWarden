import { lazy, Suspense } from 'react'
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
import ConnectBiPage from './setup/ConnectBiPage'
import EntryTemplatesPage from './setup/EntryTemplatesPage'
import HelpPage from './setup/HelpPage'
import ImportPage from './setup/ImportPage'
import PayeesPage from './setup/PayeesPage'
import ScenariosPage from './setup/ScenariosPage'
import ScheduledPage from './setup/ScheduledPage'
import SettingsAccountPage from './setup/SettingsAccountPage'
import SettingsPage from './setup/SettingsPage'
import Shell from './shell/Shell'
import StagingDuplicatesPage from './staging/StagingDuplicatesPage'
import StagingPage from './staging/StagingPage'
import TagsPage from './tags/TagsPage'

// Lazy: the only page that pulls in Recharts, currently ~650KB/~180KB
// gzip of the production bundle on its own (see docs/ARCHITECTURE.md's
// "Lazy routes" section) — every other route stays in the main chunk,
// this one loads on first visit to /app/custom-report instead of on
// every page load. If a second chart-heavy page ever ships, split it
// the same way rather than pulling Recharts back into the main chunk.
const CustomReportPage = lazy(() => import('./reports/CustomReportPage'))

// Maps a real browser path to the `current` key Sidebar.tsx/Topbar.tsx
// use for active-link highlighting — deliberately a plain if-chain, not a
// lookup shared with nav.ts's own NAV_GROUPS: a link's own `key` (nav.ts)
// already has to match this independently since neither file imports
// from the other.
function routeKey(pathname: string): string {
  if (pathname === '/app/accounts') return 'accounts'
  if (pathname === '/app/tags') return 'tags'
  if (pathname === '/app/payees') return 'payees'
  if (pathname === '/app/scenarios') return 'scenarios'
  if (pathname === '/app/account-levels') return 'account_levels'
  if (pathname === '/app/scheduled') return 'scheduled'
  if (pathname === '/app/templates') return 'templates'
  if (pathname === '/app/import') return 'import'
  if (pathname === '/app/help') return 'help'
  if (pathname === '/app/settings/account') return 'settings_account'
  if (pathname === '/app/settings/connect-bi') return 'settings_connect_bi'
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
  if (pathname === '/app/custom-report') return 'custom_report'
  return 'dashboard'
}

// Shell's own topbar title, one entry per real route — a plain object
// keyed the same way `routeKey` above returns. Same `nav.ts`-independent
// duplication `routeKey` already accepts (see its own comment) rather
// than importing NAV_GROUPS' own labels, which aren't keyed for a 1:1
// lookup this cheap anyway.
const PAGE_TITLES: Record<string, string> = {
  accounts: 'Accounts',
  tags: 'Tags',
  payees: 'Payees',
  scenarios: 'Scenarios',
  account_levels: 'Account levels',
  scheduled: 'Scheduled Entries',
  templates: 'Templates',
  import: 'Import',
  help: 'Help',
  settings: 'Settings',
  settings_account: 'Account',
  settings_connect_bi: 'Connect Power BI / Excel',
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
  custom_report: 'Report Builder',
}

// Root component. Three-way branch on `session.status`, matching the
// backend's own `auth_gate`'s "redirect to /login, or don't" logic —
// just without a redirect, since `LoginPage` and the authenticated app
// are both this one component tree, not two different server-rendered
// pages.
//
// The authenticated branch renders a real `<Routes>` (`/app/tags`, not
// the bare `/tags` GET /tags itself already owns; see main.py's own
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
        <Route path="/app/import" element={<ImportPage />} />
        <Route path="/app/help" element={<HelpPage />} />
        <Route path="/app/settings" element={<SettingsPage />} />
        <Route path="/app/settings/account" element={<SettingsAccountPage />} />
        <Route path="/app/settings/connect-bi" element={<ConnectBiPage />} />
        <Route path="/app/trial-balance" element={<TrialBalancePage />} />
        <Route path="/app/balance-sheet" element={<BalanceSheetPage />} />
        <Route path="/app/cash-flow" element={<CashFlowPage />} />
        <Route path="/app/income-statement" element={<IncomeStatementPage />} />
        <Route path="/app/variance" element={<VariancePage />} />
        <Route path="/app/ledger" element={<LedgerPage />} />
        <Route path="/app/custom-report" element={
          <Suspense fallback={<p>Loading…</p>}>
            <CustomReportPage />
          </Suspense>
        } />
        <Route path="/app/entries" element={<JournalPage />} />
        <Route path="/app/staging" element={<StagingPage />} />
        <Route path="/app/staging/duplicates" element={<StagingDuplicatesPage />} />
        <Route path="/app/budget" element={<BudgetPage />} />
      </Routes>
    </Shell>
  )
}

export default App
