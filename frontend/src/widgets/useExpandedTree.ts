import { useEffect, useMemo, useState } from 'react'
import type { ExpandedState, OnChangeFn } from '@tanstack/react-table'

import { loadCollapsed } from './useCollapsibleTree'

// The TanStack Table equivalent of useCollapsibleTree.ts, for reports
// ported to a real `useReactTable` instance (ROADMAP.md S1 — Trial
// Balance and Balance Sheet so far). Two responsibilities split across
// two exports, mirroring why the old hook bundled them: nesting a flat,
// `parent_id`-linked row list into the shape `getSubRows` expects, and
// translating this app's own collapsed-id persistence into TanStack's
// own `expanded` state contract.

export interface TreeRow {
  id?: number
  parent_id?: number | null
  has_children: boolean
}

export type TreeNode<T extends TreeRow> = T & { subRows: TreeNode<T>[] }

// Nests a flat row list by `parent_id` into `subRows` arrays, the shape
// `getSubRows: (row) => row.subRows` expects. A row with no `id` is never
// linked to (mirrors useCollapsibleTree's own "such a row is never
// registered" rule) and is emitted as its own root rather than dropped —
// silently losing a row would be worse than misplacing one that was never
// supposed to exist per that same rule.
//
// Preserves each level's original relative order: the report APIs already
// emit a parent immediately before its own children (`flatten_tree()`
// server-side), and a `Map`'s insertion order plus `Array.push` here just
// carries that ordering through into `subRows` untouched — no explicit
// sort needed.
export function buildRowTree<T extends TreeRow>(rows: T[]): TreeNode<T>[] {
  const byId = new Map<number, TreeNode<T>>()
  for (const row of rows) if (row.id !== undefined) byId.set(row.id, { ...row, subRows: [] })

  const roots: TreeNode<T>[] = []
  for (const row of rows) {
    if (row.id === undefined) {
      roots.push({ ...row, subRows: [] })
      continue
    }
    const node = byId.get(row.id)!
    const parent = row.parent_id != null ? byId.get(row.parent_id) : undefined
    if (parent) parent.subRows.push(node)
    else roots.push(node)
  }
  return roots
}

export interface ExpandedTreeState {
  expanded: ExpandedState
  onExpandedChange: OnChangeFn<ExpandedState>
}

// Same storage key, same on-disk array-of-collapsed-ids shape as
// useCollapsibleTree — only the in-memory representation changes, from a
// raw Set an ancestor-walk reads directly to the `ExpandedState` record
// `getExpandedRowModel` expects (which itself already does the
// ancestor-walk: a row under a collapsed parent is excluded from
// `getRowModel().rows` regardless of its own entry).
//
// TanStack treats a row missing from the record as collapsed — the
// opposite of this app's own default (expanded unless the user explicitly
// collapsed it) — so every row with a known id gets an explicit entry
// every render, not just the ones actually collapsed.
export function useExpandedTree(storageKey: string, rows: TreeRow[]): ExpandedTreeState {
  const [collapsed, setCollapsed] = useState<Set<number>>(() => loadCollapsed(storageKey))

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(Array.from(collapsed)))
  }, [storageKey, collapsed])

  const expanded = useMemo(() => {
    const record: Record<string, boolean> = {}
    for (const row of rows) if (row.id !== undefined) record[String(row.id)] = !collapsed.has(row.id)
    return record
  }, [rows, collapsed])

  const onExpandedChange: OnChangeFn<ExpandedState> = (updater) => {
    setCollapsed((prevCollapsed) => {
      const prevExpanded: Record<string, boolean> = {}
      for (const row of rows) if (row.id !== undefined) prevExpanded[String(row.id)] = !prevCollapsed.has(row.id)
      const nextExpanded = typeof updater === 'function' ? updater(prevExpanded) : updater

      // `row.toggleExpanded()` (table-core's own RowExpanding feature)
      // collapses a row by *deleting* its key from the record it hands to
      // this updater, not by setting it to `false` — it relies on its own
      // `row.getIsExpanded()` treating a missing key as falsy. Checking
      // `=== false` here missed that: a deleted key silently read as
      // "still expanded," so a click did nothing. `!nextExpanded[id]`
      // catches both an explicit `false` and a missing key, matching
      // table-core's own definition of "not expanded."
      const nextCollapsed = new Set<number>()
      if (nextExpanded !== true) {
        for (const row of rows) {
          if (row.id !== undefined && !nextExpanded[String(row.id)]) nextCollapsed.add(row.id)
        }
      }
      return nextCollapsed
    })
  }

  return { expanded, onExpandedChange }
}
