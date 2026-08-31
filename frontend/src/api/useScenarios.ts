import { useEffect, useState } from 'react'

import client from './client'

// GET /scenarios's own response is a plain `list[dict]`
// (`modules/reference/router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}[]` — same gap `useAppConfig.ts`/
// `tags/TagsPage.tsx` already document for their own plain-dict routes,
// cast through this local interface instead. Only the fields a picker
// actually needs are typed; `repository.scenarios_all`'s own extra
// columns (`base_level_name`, ...) are real but unused here.
//
// `is_staging`/`is_locked`/`income_statement_only`/`enforce_balance`/
// `base_level_id` are what `NewEntryPanel.tsx` needs to filter locked/
// income-statement-only/staging scenarios out of the New entry picker,
// and to drive the balance-bar's own `enforcing()` check. `entry_count`
// (real on the wire via `repository.py`'s `scenarios_all()`) is what
// Trial Balance and Variance use to tell "this scenario has never had
// anything posted to it" apart from "this scenario has entries, just
// none in the selected window," which a bare empty-grid can't
// distinguish on its own.
export interface Scenario {
  id: number
  code: string
  name: string
  scenario_type: string
  is_locked: boolean
  is_staging: boolean
  income_statement_only: boolean
  enforce_balance: boolean
  base_level_id: number | null
  entry_count: number
}

// A plain hook, not a Context/Provider — same call `useAppConfig.ts`
// already made for the identical shape (one-shot GET, no writer other
// than the server itself, more than one caller likely but none of them
// needs to see another's request in flight). Every report/Journal/
// Budget screen needing the scenario list reuses this rather than each
// hand-rolling its own `client.GET('/scenarios')`.
export function useScenarios(): Scenario[] | null {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/scenarios').then(({ data }) => {
      if (!cancelled && data) setScenarios(data as unknown as Scenario[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return scenarios
}
