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

// Mirrors app/templates/base.html's sidebar exactly — same three groups,
// same order, same link labels/paths.
//
// The Books group's own `key` stays "ledger", not "books" — an arbitrary
// localStorage identifier (see useSidebarGroupCollapse), left alone for
// the same reason base.html's own comment gives: it has no coupling to
// the visible "Books" label, so a future rename doesn't reset anyone's
// saved collapse state. It happens to equal the Ledger *report* link's
// own `key` below, in the Reports group — harmless, since group keys and
// link keys are never compared to each other, only within their own
// list (group key -> collapse storage, link key -> active-link match).
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'ledger',
    label: 'Books',
    links: [
      { key: 'entries', label: 'Journal', href: '/entries' },
      { key: 'staging', label: 'Staging', href: '/staging' },
      { key: 'scheduled', label: 'Scheduled Entries', href: '/scheduled' },
      { key: 'import', label: 'Import', href: '/import' },
      { key: 'templates', label: 'Templates', href: '/templates' },
      { key: 'budget', label: 'Budget Grid', href: '/budget' },
    ],
  },
  {
    key: 'reports',
    label: 'Reports',
    links: [
      { key: 'balance_sheet', label: 'Balance Sheet', href: '/balance-sheet' },
      { key: 'income_statement', label: 'Income Statement', href: '/income-statement' },
      { key: 'cash_flow', label: 'Cash Flow', href: '/cash-flow' },
      { key: 'variance', label: 'Variance', href: '/variance' },
      { key: 'tb', label: 'Trial Balance', href: '/trial-balance' },
      { key: 'ledger', label: 'Ledger', href: '/ledger' },
    ],
  },
  {
    key: 'setup',
    label: 'Setup',
    links: [
      { key: 'accounts', label: 'Accounts', href: '/accounts' },
      { key: 'account_levels', label: 'Levels', href: '/account-levels' },
      { key: 'scenarios', label: 'Scenarios', href: '/scenarios' },
      { key: 'payees', label: 'Payees', href: '/payees' },
      { key: 'tags', label: 'Tags', href: '/tags' },
      { key: 'help', label: 'Help', href: '/help' },
    ],
  },
]
