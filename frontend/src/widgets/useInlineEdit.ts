import { useRef, useState } from 'react'

const AUTOSAVE_DEBOUNCE_MS = 600

export interface InlineEditResult {
  ok: boolean
  value?: string
  error?: string
}

interface UseInlineEditOptions {
  // A draft can autosave blank (memo — `.memo-cell`) or never (an entry's
  // own description, which the server already refuses to store empty) —
  // `description-edit.js`'s own point 2 for keeping it a separate file
  // from `memo-edit.js` rather than one shared abstraction. This flag is
  // the one behavioral knob that difference actually reduces to; the
  // other (stopping `<summary>`'s native toggle on click) is a DOM
  // concern the *caller* handles, not this hook.
  allowBlank: boolean
  // Called after any save actually lands on the server — both the
  // debounced autosave and the final commit — so the caller's own copy
  // (the Journal's `entries` list, held in `JournalPage.tsx` state, not
  // re-fetched on every keystroke) stays in sync with what's really
  // there. Not called for a `cancel()` that never sent a corrective POST
  // (nothing changed to report).
  onSaved?: (value: string) => void
}

export interface InlineEditState {
  editing: boolean
  draft: string
  start: () => void
  onChange: (value: string) => void
  commit: () => void
  cancel: () => void
}

// Shared debounce-autosave-with-corrective-cancel mechanics behind both
// `DescriptionCell.tsx` and `MemoCell.tsx` (Phase 3.4) — the part of
// `description-edit.js`/`memo-edit.js` with nothing field-specific about
// it (same factoring judgment `useCollapsibleTree.ts`/`useSelectMode.ts`
// already made for their own legacy JS pairs/trios). The two source
// files stayed deliberately separate in vanilla JS ("two files this
// close in shape is exactly the amount of duplication worth keeping
// simple... a third such widget would be the point to actually factor
// one out") — but that reasoning was about the cost of *sharing* in
// hand-wired DOM code, not about React hooks: a bug fixed once here
// benefits both cells for free, at no coordination cost, so sharing it
// is the better default in this codebase, not a departure from that
// call.
//
// The iPad bug this whole pattern exists to survive (BACKLOG.md — a
// hardware-keyboard setup where blur/Enter's own save never landed) is
// why a draft autosaves on a debounce *while still typing*, independent
// of whatever eventually closes the field — and why `cancel()` has to
// actively re-POST the pre-edit value if a debounced draft already beat
// it to the server, not just repaint the old text locally. See
// `memo-edit.js`'s own file comment for the full writeup; nothing about
// the reasoning changed in this port, only the mechanism (React state
// instead of a raw DOM `<input>` swapped into a cell).
export function useInlineEdit(
  serverValue: string,
  save: (value: string) => Promise<InlineEditResult>,
  { allowBlank, onSaved }: UseInlineEditOptions,
): InlineEditState {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(serverValue)
  // What the server currently holds — starts at whatever this edit began
  // from, moves forward as an autosave lands, so `cancel()` knows
  // whether it has anything to undo. A ref, not state: read/written only
  // from event handlers and a debounce timer, never rendered.
  const onServer = useRef(serverValue)
  const timer = useRef<number | null>(null)
  const done = useRef(true)

  function clearTimer() {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }

  function start() {
    if (!done.current) return // already editing
    onServer.current = serverValue
    setDraft(serverValue)
    done.current = false
    setEditing(true)
  }

  function autosave(value: string) {
    timer.current = null
    if (done.current) return
    const v = value.trim()
    if (v === onServer.current) return
    if (!allowBlank && !v) return // never autosave blank for a field that can't hold one
    save(v)
      .then((data) => {
        if (data.ok) {
          onServer.current = v
          onSaved?.(v)
        }
      })
      .catch(() => {}) // a final save (blur/Enter) or the next debounce tick will retry
  }

  function onChange(value: string) {
    setDraft(value)
    clearTimer()
    timer.current = window.setTimeout(() => autosave(value), AUTOSAVE_DEBOUNCE_MS)
  }

  function cancel() {
    if (done.current) return
    done.current = true
    clearTimer()
    if (onServer.current !== serverValue) save(serverValue).catch(() => {})
    setEditing(false)
  }

  function commit() {
    if (done.current) return
    done.current = true
    clearTimer()
    const v = draft.trim()
    if (!v && !allowBlank) {
      // Can't save blank — same outcome as cancel().
      if (onServer.current !== serverValue) save(serverValue).catch(() => {})
      setEditing(false)
      return
    }
    if (v === onServer.current) {
      setEditing(false)
      return
    }
    save(v)
      .then((data) => {
        if (data.ok) onSaved?.(data.value ?? v)
      })
      .catch(() => {})
      .finally(() => setEditing(false))
  }

  return { editing, draft, start, onChange, commit, cancel }
}
