import { useEffect, useState } from 'react'

import client from './client'

// GET /scenarios's own response is a plain `list[dict]`
// (`modules/reference/router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}[]` — same gap `useAppConfig.ts`/
// `tags/TagsPage.tsx` already document for their own plain-dict routes,
// cast through this local interface instead. Only the fields a picker
// actually needs are typed; `repository.scenarios_all`'s own extra
// columns (`base_level_name`, `entry_count`, ...) are real but unused
// here.
//
// Widened for Phase 3.4 (the Journal): `is_staging`/`is_locked`/
// `income_statement_only`/`enforce_balance`/`base_level_id` are what
// `NewEntryPanel.tsx` needs to reproduce legacy `entries_page`'s own
// `new_entry_scenarios` filter (excludes locked/income-statement-only/
// staging scenarios from the New entry picker) and the balance-bar's
// `enforcing()` check — Trial Balance's own Phase 3.3 usage only ever
// read `code`/`name`/`is_locked`, so this is a strict superset, not a
// breaking change to that call site.
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
}

// A plain hook, not a Context/Provider — same call `useAppConfig.ts`
// already made for the identical shape (one-shot GET, no writer other
// than the server itself, more than one caller likely but none of them
// needs to see another's request in flight). First caller is Trial
// Balance's own scenario picker (Phase 3.3); every other report/Journal/
// Budget screen needing the same list reuses this unchanged rather than
// each hand-rolling its own `client.GET('/scenarios')`.
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
