import { useEffect, useMemo, useState } from 'react'

// The collapsible-account-hierarchy mechanics shared by every
// account-tree table in the app (Trial Balance, Balance Sheet), generic
// over any numeric id list the same way `useSelectMode` is. Collapse
// state persists per browser in `localStorage`, keyed by `storageKey` —
// one constant per report page, not scenario/date-scoped, so paging
// through months or switching scenarios doesn't reset which sections a
// viewer already collapsed.
//
// A row with no `id` at all is never registered in `byId` and never
// hidden by an ancestor's collapse — this hook is deliberately never
// asked to track such rows. Trial Balance/Balance Sheet's synthetic
// "Retained Earnings" node isn't one of them: `domain.accounts.
// earnings_rows` gives it real (reserved, negative-sentinel) ids
// specifically so it's a genuine collapsible parent/children unit like
// any real account.
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

  // Walks the parent chain — a row is hidden if *any* ancestor (not just
  // its direct parent) is collapsed, so collapsing a grandparent hides
  // everything under it in one click without the intermediate parent
  // also needing to be marked collapsed itself.
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
