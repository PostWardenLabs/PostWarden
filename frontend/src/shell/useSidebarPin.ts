import { useCallback, useEffect, useRef, useState } from 'react'

const PIN_KEY = 'postwarden-sidebar-pinned'

// Hover the hamburger (or the sidebar panel itself) to preview the menu;
// click it to pin the sidebar open instead. 200ms close grace period
// (moving the mouse from the hamburger to the panel crosses a real gap —
// closing on that crossing would mean the menu shuts before the pointer
// arrives), Escape closes an unpinned preview, pin state persists to
// localStorage.
//
// `html.sidebar-pinned` is read by index.html's own pre-paint script
// before React ever mounts (so a pinned sidebar doesn't flash unpinned on
// load), so this hook writes that class straight to
// document.documentElement itself rather than letting React own it
// indirectly through some wrapper element's className — there is no
// wrapper element positioned to hold it; the class has to be the single
// source of truth right where the pre-paint script already put it.
export function useSidebarPin() {
  const [pinned, setPinned] = useState(() =>
    document.documentElement.classList.contains('sidebar-pinned'),
  )
  const [open, setOpen] = useState(pinned)
  const closeTimer = useRef<number | null>(null)

  const clearCloseTimer = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }, [])

  const previewOpen = useCallback(() => {
    clearCloseTimer()
    setOpen(true)
  }, [clearCloseTimer])

  const scheduleClose = useCallback(() => {
    if (pinned) return
    clearCloseTimer()
    closeTimer.current = window.setTimeout(() => setOpen(false), 200)
  }, [pinned, clearCloseTimer])

  const toggle = useCallback(() => {
    const next = !pinned
    if (next) {
      document.documentElement.classList.add('sidebar-pinned')
      localStorage.setItem(PIN_KEY, '1')
      setOpen(true)
    } else {
      document.documentElement.classList.remove('sidebar-pinned')
      localStorage.removeItem(PIN_KEY)
      setOpen(false)
    }
    setPinned(next)
  }, [pinned])

  // Escape closes an unpinned (hover-previewed) sidebar without having to
  // move the mouse back out over it.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !pinned) setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [pinned])

  useEffect(() => clearCloseTimer, [clearCloseTimer])

  return { pinned, open, previewOpen, scheduleClose, toggle }
}
