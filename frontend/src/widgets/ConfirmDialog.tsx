import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { ConfirmContext, type ConfirmFn, type ConfirmOptions } from './confirmContext'

interface ConfirmState extends ConfirmOptions {
  message: string
  resolve: (result: boolean) => void
}

// A confirm dialog that actually looks like the app, not the browser's
// own unstyleable alert skin. Same true/false Promise shape as the
// native confirm() it replaces, just asynchronous — awaiting a click
// instead of blocking the whole page (see confirmContext.ts's
// useConfirm()).
//
// Every write in the SPA goes through a typed API call a component
// controls directly, so there's no bare `<form>` submit to intercept —
// call `useConfirm()`'s returned function directly at the point a
// destructive action is triggered instead.
//
// Mounted once, near the app root (see main.tsx), as a singleton overlay
// via a Provider.
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConfirmState | null>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const okRef = useRef<HTMLButtonElement>(null)

  const ask = useCallback<ConfirmFn>((message, opts = {}) => {
    previouslyFocused.current = document.activeElement as HTMLElement | null
    return new Promise<boolean>((resolve) => {
      setState({ message, resolve, ...opts })
    })
  }, [])

  // Plain closure over the current `state`, not a setState updater —
  // this only ever runs from a real user-triggered event (a button
  // click, a keydown), same reasoning as useSidebarPin's toggle().
  function settle(result: boolean) {
    if (!state) return
    state.resolve(result)
    setState(null)
    const el = previouslyFocused.current
    if (el && document.contains(el)) el.focus()
  }

  // Cancel gets initial focus regardless of danger — a stray Enter press
  // should never be the thing that confirms a destructive action.
  useEffect(() => {
    if (state) cancelRef.current?.focus()
  }, [state])

  // Escape cancels; a tiny two-item focus trap keeps Tab/Shift+Tab from
  // ever leaving the modal while it's open — same expectation as any
  // real dialog.
  useEffect(() => {
    if (!state) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        settle(false)
        return
      }
      if (e.key !== 'Tab') return
      const items = [cancelRef.current, okRef.current].filter((el): el is HTMLButtonElement => !!el)
      e.preventDefault()
      const i = items.indexOf(document.activeElement as HTMLButtonElement)
      const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === items.length - 1 ? 0 : i + 1
      items[next]?.focus()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {state && (
        <div
          className="confirm-overlay"
          onMouseDown={(e) => {
            // Clicking the dimmed backdrop cancels, same as clicking
            // outside any other popover in this app.
            if (e.target === e.currentTarget) settle(false)
          }}
        >
          <div
            className="confirm-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-message"
          >
            <p className="confirm-message" id="confirm-message">
              {state.message}
            </p>
            <div className="confirm-actions">
              <button
                ref={cancelRef}
                type="button"
                className="quiet confirm-cancel"
                onClick={() => settle(false)}
              >
                {state.cancelLabel || 'Cancel'}
              </button>
              <button
                ref={okRef}
                type="button"
                className={'confirm-ok' + (state.danger ? ' danger' : '')}
                onClick={() => settle(true)}
              >
                {state.okLabel || 'OK'}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
