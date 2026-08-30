import { useMemo } from 'react'

import type { Account } from '../api/useAccounts'
import { useAccounts } from '../api/useAccounts'
import type { AccountLevel } from '../api/useAccountLevels'
import { useAccountLevels } from '../api/useAccountLevels'
import type { Scenario } from '../api/useScenarios'

// Ported from app/main.py's `postable_accounts_for_pickers`/
// `postable_accounts_by_scenario` (Phase 3.4) — client-side, since
// REBUILD.md decision 3 draws the line at "the frontend fetches
// reference data separately," not at "the frontend re-derives nothing
// from it." Both legacy functions are pure filters over data this hook
// already has via `useAccounts`/`useAccountLevels`/the caller's own
// `useScenarios` — recomputing them here means the New entry account
// picker doesn't need a bespoke backend endpoint just to answer "which
// accounts can this scenario actually post to," matching
// `fn_line_account_guard` exactly (the same rule the database itself
// enforces at commit): a leaf (`is_postable`) account, or — when a
// scenario has its own `base_level_id` — anything sitting at that
// level's own `depth`.
export interface PostableAccount {
  id: number
  code: string
  name: string
  path: string
}

export interface PostableAccounts {
  // Every account ANY scenario could post to, the union across all of
  // them — legacy's own "no single scenario to be precise about" case
  // (entry_templates.html isn't scenario-bound). Used for the Journal's
  // own filter-bar Account picker, which has no scenario context to
  // narrow against either.
  forPickers: PostableAccount[]
  // {scenario_id: [...]}, each scenario's own exact posting targets —
  // the New entry panel's account picker re-keys into this whenever the
  // Scenario field changes (see NewEntryPanel.tsx's own
  // refreshAccountsForScenario, ported from app.js's).
  byScenario: Map<number, PostableAccount[]>
}

function toPostable(a: Account): PostableAccount {
  return { id: a.id, code: a.code, name: a.name, path: a.path }
}

export function usePostableAccounts(scenarios: Scenario[] | null): PostableAccounts | null {
  const accounts = useAccounts()
  const levels = useAccountLevels()

  return useMemo(() => {
    if (!accounts || !levels || !scenarios) return null
    const depthByLevelId = new Map<number, number>(levels.map((l: AccountLevel) => [l.id, l.depth]))
    const active = accounts.filter((a) => a.is_active)

    const levelDepths = new Set(
      scenarios.filter((s) => s.base_level_id != null).map((s) => depthByLevelId.get(s.base_level_id!)),
    )
    const forPickers = active
      .filter((a) => a.is_postable || levelDepths.has(a.depth))
      .map(toPostable)

    const byScenario = new Map<number, PostableAccount[]>()
    for (const s of scenarios) {
      const baseDepth = s.base_level_id != null ? depthByLevelId.get(s.base_level_id) : undefined
      byScenario.set(
        s.id,
        active.filter((a) => a.is_postable || (baseDepth !== undefined && a.depth === baseDepth)).map(toPostable),
      )
    }
    return { forPickers, byScenario }
  }, [accounts, levels, scenarios])
}
