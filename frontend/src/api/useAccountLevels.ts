import { useEffect, useState } from 'react'

import client from './client'

// GET /account-levels's own response is a plain `list[dict]`
// (`modules/reference/repository.py`'s own `account_levels_all`), same
// cast-through-a-local-interface gap every other reference hook already
// documents. `usePostableAccounts.ts` needs `id` -> `depth` to resolve a
// scenario's own `base_level_id` into the depth `fn_line_account_guard`
// actually posts against — `name`/`scenario_count` are real
// (`account_levels_all`'s own extra column) but unused here.
export interface AccountLevel {
  id: number
  name: string
  depth: number
}

export function useAccountLevels(): AccountLevel[] | null {
  const [levels, setLevels] = useState<AccountLevel[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/account-levels').then(({ data }) => {
      if (!cancelled && data) setLevels(data as unknown as AccountLevel[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return levels
}
