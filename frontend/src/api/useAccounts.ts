import { useEffect, useState } from 'react'

import client from './client'

// GET /accounts's own response is a plain `list[dict]` straight off
// `v_dim_account` (`modules/reference/repository.py`'s own `list_accounts`
// docstring), so openapi-fetch can only type it as
// `{[key: string]: unknown}[]` — same gap `useScenarios.ts` already
// documents for its own plain-dict route, cast through this local
// interface instead. First caller is the Journal's `usePostableAccounts.ts`
// (Phase 3.4), which needs `is_postable`/`is_active`/`depth` to reproduce
// legacy's `postable_accounts_for_pickers`/`postable_accounts_by_scenario`
// filtering client-side — every other field `v_dim_account` carries
// (`parent_id`, `parent_path`, `sort_path`, `normal_side`, `account_type`,
// `is_cashflow`) is real but unused here; Accounts' own CRUD screen
// (Phase 4.6) is a more likely second caller than a reason to trim this
// down further now.
export interface Account {
  id: number
  code: string
  name: string
  path: string
  depth: number
  is_postable: boolean
  is_active: boolean
}

// A plain one-shot hook, same shape as `useScenarios.ts` — see that
// file's own comment for why this isn't a Context/Provider.
export function useAccounts(): Account[] | null {
  const [accounts, setAccounts] = useState<Account[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/accounts').then(({ data }) => {
      if (!cancelled && data) setAccounts(data as unknown as Account[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return accounts
}
