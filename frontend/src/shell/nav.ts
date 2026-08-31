export interface NavLink {
  key: string
  label: string
  href: string
}

export interface NavGroup {
  key: string
  label: string
  links: NavLink[]
}

// The sidebar's three groups, in order, with their link labels/paths.
//
// The Books group's own `key` stays "ledger", not "books" — an arbitrary
// localStorage identifier (see useSidebarGroupCollapse) with no coupling
// to the visible "Books" label, so a future rename doesn't reset
// anyone's saved collapse state. It happens to equal the Ledger *report*
// link's
// own `key` below, in the Reports group — harmless, since group keys and
// link keys are never compared to each other, only within their own
// list (group key -> collapse storage, link key -> active-link match).
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'ledger',
    label: 'Books',
    links: [
      { key: 'entries', label: 'Journal', href: '/app/entries' },
      { key: 'staging', label: 'Staging', href: '/app/staging' },
      { key: 'scheduled', label: 'Scheduled Entries', href: '/app/scheduled' },
      { key: 'import', label: 'Import', href: '/app/import' },
      { key: 'templates', label: 'Templates', href: '/app/templates' },
      { key: 'budget', label: 'Budget Grid', href: '/app/budget' },
    ],
  },
  {
    key: 'reports',
    label: 'Reports',
    links: [
      { key: 'balance_sheet', label: 'Balance Sheet', href: '/app/balance-sheet' },
      { key: 'income_statement', label: 'Income Statement', href: '/app/income-statement' },
      { key: 'cash_flow', label: 'Cash Flow', href: '/app/cash-flow' },
      { key: 'variance', label: 'Variance', href: '/app/variance' },
      { key: 'tb', label: 'Trial Balance', href: '/app/trial-balance' },
      { key: 'ledger', label: 'Ledger', href: '/app/ledger' },
      { key: 'custom_report', label: 'Report Builder', href: '/app/custom-report' },
    ],
  },
  {
    key: 'setup',
    label: 'Setup',
    links: [
      { key: 'accounts', label: 'Accounts', href: '/app/accounts' },
      { key: 'account_levels', label: 'Levels', href: '/app/account-levels' },
      { key: 'scenarios', label: 'Scenarios', href: '/app/scenarios' },
      { key: 'payees', label: 'Payees', href: '/app/payees' },
      { key: 'tags', label: 'Tags', href: '/app/tags' },
      { key: 'help', label: 'Help', href: '/app/help' },
    ],
  },
]
