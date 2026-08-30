import { useEffect, useState } from 'react'

import client from './client'

// GET /accounts's own response is a plain `list[dict]` straight off
// `v_dim_account` (`modules/reference/repository.py`'s own `list_accounts`
// docstring), so openapi-fetch can only type it as
// `{[key: string]: unknown}[]` — same gap `useScenarios.ts` already
// documents for its own plain-dict route, cast through this local
// interface instead. First caller is the Journal's `usePostableAccounts.ts`
// (Phase 3.4), which only needed `is_postable`/`is_active`/`depth`;
// `account_type`/`parent_id`/`is_cashflow`/`parent_path` were added in
// Phase 4.6 for Accounts' own CRUD screen, the second caller this file's
// own comment anticipated — `sort_path`/`normal_side` are still real but
// unused by either caller (the former because `v_dim_account` already
// arrives pre-sorted by it; the latter has no caller at all yet).
export type AccountType = 'asset' | 'liability' | 'equity' | 'income' | 'expense'

export interface Account {
  id: number
  code: string
  name: string
  account_type: AccountType
  parent_id: number | null
  path: string
  parent_path: string | null
  depth: number
  is_postable: boolean
  is_active: boolean
  is_cashflow: boolean
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
