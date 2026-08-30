import { useEffect, useRef } from 'react'

interface MergeDialogProps {
  open: boolean
  count: number
  labelPlural: string
  initialName: string
  onCancel: () => void
  onConfirm: (name: string) => void
}

// Ported from entity-manage.js's Merge popup (Phase 3.2) — reuses
// ConfirmDialog.tsx's own `.confirm-overlay`/`.confirm-modal`/
// `.confirm-actions` CSS (already generic, per that file's own Phase 2.5
// comment) rather than inventing a second modal look, but isn't built on
// `useConfirm()` itself: that context's `ask()` only ever resolves a
// boolean, and a merge needs to hand back the typed survivor name too, so
// this is a plain controlled component TagsPage.tsx renders directly,
// the same way LoginPage.tsx owns its own form state rather than reaching
// for shared context that doesn't fit its own shape.
//
// Uncontrolled input (a ref, not value/onChange) — nothing else on the
// page needs to react to a keystroke while this is open, so there's no
// reason to re-render on every one; `defaultValue` reruns only when
// `initialName` itself changes (i.e., a fresh open with a different first
// checked row).
//
// Deliberately has no Tab focus trap, unlike ConfirmDialog.tsx's own
// cancel/OK loop — a real, pre-existing gap in legacy's own
// entity-manage.js (its `build()` wires an Escape listener but never a
// Tab one, unlike confirm.js's dialog), ported as-is rather than fixed,
// per REBUILD.md decision 4.
export default function MergeDialog({
  open, count, labelPlural, initialName, onCancel, onConfirm,
}: MergeDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onCancel])

  if (!open) return null

  function submit() {
    const name = inputRef.current?.value.trim()
    if (!name) {
      inputRef.current?.focus()
      return
    }
    onConfirm(name)
  }

  return (
    <div
      className="confirm-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div className="confirm-modal" role="dialog" aria-label={`Merge ${labelPlural}`}>
        <h3 className="merge-heading">
          Merge {count} {labelPlural}
        </h3>
        <label className="field">
          Merge into
          <input
            ref={inputRef}
            type="text"
            required
            maxLength={80}
            defaultValue={initialName}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                submit()
              }
            }}
          />
        </label>
        <div className="confirm-actions" style={{ marginTop: '1.1rem' }}>
          <button type="button" className="quiet confirm-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="confirm-ok" onClick={submit}>
            Merge
          </button>
        </div>
      </div>
    </div>
  )
}
