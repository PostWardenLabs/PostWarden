import { useEffect, useMemo, useState } from 'react'

// Ported from report-tree.js (Phase 3.3) — the collapsible-account-
// hierarchy mechanics shared by every account-tree table in the app
// (Trial Balance/Balance Sheet today; Accounts' own level browser,
// Phase 4.6, reuses the identical id/parent_id/has_children shape once
// it exists, same generic-over-any-numeric-id-list call `useSelectMode`
// (Phase 3.2) already made for Tags/Payees). Collapse state persists per
// browser in `localStorage`, keyed by `storageKey` — same one constant
// per report page report-tree.js's own `data-collapse-key` attribute
// used, not scenario/date-scoped, so paging through months or switching
// scenarios doesn't reset which sections a viewer already collapsed.
//
// A row with no `id` at all is never registered in `byId` and never
// hidden by an ancestor's collapse — the same behavior report-tree.js's
// own `tr[data-id]` selector gave for free, since Jinja never emitted a
// `data-id` attribute on such a row's `<tr>` at all (see
// `trial_balance.html`'s own `{% if r.id is defined %}` guard). Trial
// Balance/Balance Sheet's synthetic "Retained Earnings" node used to be
// exactly this case — two flat rows with no `id`/`parent_id`, invisible
// to this hook on purpose. It isn't anymore: `domain.accounts.
// earnings_rows` now gives it real (reserved, negative-sentinel) ids
// specifically so it becomes a genuine collapsible parent/children unit
// like any real account — the id-less case above is about a row this
// hook is deliberately never asked to track, not about that feature.
export interface CollapsibleRow {
  id?: number
  parent_id?: number | null
  has_children: boolean
}

export interface CollapsibleTreeState {
  isCollapsed: (id: number) => boolean
  isHidden: (row: CollapsibleRow) => boolean
  toggle: (id: number) => void
}

function loadCollapsed(storageKey: string): Set<number> {
  try {
    return new Set(JSON.parse(localStorage.getItem(storageKey) || '[]'))
  } catch {
    return new Set()
  }
}

export function useCollapsibleTree(storageKey: string, rows: CollapsibleRow[]): CollapsibleTreeState {
  const [collapsed, setCollapsed] = useState<Set<number>>(() => loadCollapsed(storageKey))

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(Array.from(collapsed)))
  }, [storageKey, collapsed])

  const byId = useMemo(() => {
    const map = new Map<number, CollapsibleRow>()
    for (const row of rows) if (row.id !== undefined) map.set(row.id, row)
    return map
  }, [rows])

  // Walks the parent chain the same way report-tree.js's own
  // `hasCollapsedAncestor` does — a row is hidden if *any* ancestor
  // (not just its direct parent) is collapsed, so collapsing a
  // grandparent hides everything under it in one click without the
  // intermediate parent also needing to be marked collapsed itself.
  function isHidden(row: CollapsibleRow): boolean {
    let parentId = row.parent_id
    while (parentId != null) {
      if (collapsed.has(parentId)) return true
      parentId = byId.get(parentId)?.parent_id ?? null
    }
    return false
  }

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return { isCollapsed: (id) => collapsed.has(id), isHidden, toggle }
}
