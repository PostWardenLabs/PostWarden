import { useEffect, useState, type RefObject } from 'react'

export interface SelectModeState {
  selectMode: boolean
  checkedIds: Set<number>
  toggleSelectMode: () => void
  toggleChecked: (id: number) => void
  toggleSelectAll: () => void
}

// Ported from entity-manage.js's Select-mode/Merge half (Phase 3.2) — the
// part of that file with nothing entity-specific about it at all (Edit,
// the other half, stays local to each page: an inline rename form is
// different enough per entity that factoring it out here would buy
// nothing). Payees (Phase 4.2) shares this exact hook unchanged, same as
// entity-manage.js already shared one file between both legacy pages.
//
// `ids` is the full, currently-visible id list in table order — needed
// for two things a plain Set of checked ids can't answer on its own:
// "select all" needs to know the total to compare against, and the merge
// survivor is "whichever checked row sorts first in the table," not
// whichever was clicked first (TagsPage.tsx derives that by filtering its
// own sorted list against `checkedIds`, same as legacy's own
// `Array.from(table.querySelectorAll(".entity-check"))` DOM-order read).
//
// `selectAllRef` is created by the *caller* and passed in, not created
// and returned from here — a real oxlint `react(refs)` false positive
// (confirmed with a minimal repro: the plainest possible "custom hook
// returns `{ ref, ...state }`, component does `ref={hook().ref}`"
// pattern alone is enough to trigger "Cannot access refs during render"
// on every other property of that same returned object, not just the ref
// itself) is what this shape avoids, not a real render-time ref read —
// nothing below ever reads `.current` outside an effect or an event
// handler, same rule this file's own indeterminate-setting effect below
// already follows.
export function useSelectMode(
  ids: number[],
  selectAllRef: RefObject<HTMLInputElement | null>,
): SelectModeState {
  const [selectMode, setSelectMode] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set())

  // Same `body.select-mode` hook index.css's own `.select-only` rules key
  // off of — reusing the identical mechanism (and CSS) Journal/Staging's
  // own select modes already use, not a second one. Removed unconditionally
  // on unmount (not just when turning off) so navigating away mid-select
  // never leaves the class stuck for whatever screen renders next.
  useEffect(() => {
    document.body.classList.toggle('select-mode', selectMode)
    return () => document.body.classList.remove('select-mode')
  }, [selectMode])

  // React has no `indeterminate` prop — it's a DOM-only property, not an
  // HTML attribute, so it has to be set imperatively on the actual node,
  // same as legacy's own `selectAll.indeterminate = ...` line.
  useEffect(() => {
    const el = selectAllRef.current
    if (!el) return
    el.checked = checkedIds.size > 0 && checkedIds.size === ids.length
    el.indeterminate = checkedIds.size > 0 && checkedIds.size < ids.length
  }, [checkedIds, ids, selectAllRef])

  function toggleSelectMode() {
    setSelectMode((on) => {
      const next = !on
      if (!next) setCheckedIds(new Set())
      return next
    })
  }

  function toggleChecked(id: number) {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    setCheckedIds((prev) => (prev.size === ids.length ? new Set() : new Set(ids)))
  }

  return { selectMode, checkedIds, toggleSelectMode, toggleChecked, toggleSelectAll }
}
