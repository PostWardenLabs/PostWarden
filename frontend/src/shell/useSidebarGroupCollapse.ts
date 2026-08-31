import { useCallback, useState } from 'react'

const KEY_PREFIX = 'postwarden-sidebar-collapsed-'

// One localStorage key per group (`key`), not one shared key, so
// collapsing Reports doesn't touch Books' own saved state. Deliberately
// doesn't auto-expand a group just because the current page lives
// inside it — a collapsed section stays collapsed across navigation,
// same as a repo sidebar or an IDE's file tree.
export function useSidebarGroupCollapse(key: string) {
  const storageKey = KEY_PREFIX + key
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(storageKey) === '1')

  const toggle = useCallback(() => {
    const next = !collapsed
    localStorage.setItem(storageKey, next ? '1' : '0')
    setCollapsed(next)
  }, [collapsed, storageKey])

  return { collapsed, toggle }
}
