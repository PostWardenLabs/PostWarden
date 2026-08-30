import { useEffect, useRef, useState } from 'react'

import client from '../api/client'
import TagInput from '../widgets/TagInput'

interface BulkTagsDialogProps {
  open: boolean
  entryIds: string[]
  // The union of tags across whatever's checked, recomputed by the
  // caller (`JournalPage.tsx`) each time this opens — this component
  // only owns what happens *after* that starting point.
  initialTags: string[]
  allTags: string[]
  // `changed` tells the caller whether to reload the entries list (tag
  // badges are server-rendered from each entry's own fetched `tags`
  // array, not live-updated locally) — same "reload if anything actually
  // changed" contract tags-bulk-edit.js's own `closePopup()` had.
  onClose: (changed: boolean) => void
}

// Ported from app/static/tags-bulk-edit.js (Phase 3.4) — the Journal's
// "Edit tags" popup: adding a chip adds that tag to every checked entry
// that doesn't already have it, removing one drops it from every checked
// entry that does, applied live (one `POST /entries/tags` per chip
// add/remove) rather than batched behind a Save button — there is none,
// same as legacy. Reuses `ConfirmDialog.tsx`'s own `.confirm-overlay`/
// `.confirm-modal` look (an `<h3>` heading plus `TagInput.tsx` instead of
// a message and Cancel/OK, matching legacy's own reuse of confirm.js's
// CSS for this exact popup) — same non-`useConfirm()` reasoning
// `MergeDialog.tsx` already gives: this needs to run a side effect per
// keystroke-equivalent, not just resolve a boolean once.
export default function BulkTagsDialog({ open, entryIds, initialTags, allTags, onClose }: BulkTagsDialogProps) {
  const [current, setCurrent] = useState('')
  const previous = useRef<Set<string>>(new Set())
  const changed = useRef(false)
  const modalRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    previous.current = new Set(initialTags)
    changed.current = false
    setCurrent(initialTags.join(','))
    modalRef.current?.querySelector<HTMLInputElement>('input[type="text"]')?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only on open, not on every initialTags identity change
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose(changed.current)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  function postChange(tag: string, action: 'add' | 'remove') {
    return client.POST('/entries/tags', { body: { entry_ids: entryIds, action, tag } })
  }

  function handleChange(csv: string) {
    setCurrent(csv)
    const next = new Set(csv.split(',').map((s) => s.trim()).filter(Boolean))
    for (const t of next) {
      if (!previous.current.has(t)) postChange(t, 'add')
    }
    for (const t of previous.current) {
      if (!next.has(t)) postChange(t, 'remove')
    }
    previous.current = next
    changed.current = true
  }

  return (
    <div
      className="confirm-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose(changed.current)
      }}
    >
      <div className="confirm-modal" role="dialog" aria-label="Edit tags" ref={modalRef}>
        <h3>Edit Tags</h3>
        <TagInput value={current} onChange={handleChange} suggestions={allTags} placeholder="Add a tag…" />
        <div className="confirm-actions" style={{ marginTop: '1.1rem' }}>
          <button type="button" className="confirm-ok" onClick={() => onClose(changed.current)}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
