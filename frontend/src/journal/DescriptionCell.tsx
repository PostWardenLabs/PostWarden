import { useEffect, useRef } from 'react'

import client from '../api/client'
import { useInlineEdit } from '../widgets/useInlineEdit'

interface DescriptionCellProps {
  entryId: string
  description: string
  onSaved: (value: string) => void
}

// Ported from app/static/description-edit.js (Phase 3.4) — click-to-edit
// for an entry's own description, sharing `useInlineEdit`'s debounce/
// autosave/corrective-cancel mechanics with `MemoCell.tsx`. This cell
// lives *inside* `<summary>` (see `JournalPage.tsx`'s own comment on
// why, matching entries.html's structure), so a click here has to stop
// `<summary>`'s native "click anywhere inside toggles the panel"
// behavior — `e.preventDefault()` on the wrapping span's own onClick,
// the documented way to cancel that default, same as description-edit.js.
export default function DescriptionCell({ entryId, description, onSaved }: DescriptionCellProps) {
  const edit = useInlineEdit(
    description,
    async (value) => {
      const { data, error } = await client.POST('/entries/{entry_id}/edit-description', {
        params: { path: { entry_id: entryId } },
        body: { description: value },
      })
      if (error) return { ok: false }
      const body = data as unknown as { description: string }
      return { ok: true, value: body.description }
    },
    { allowBlank: false, onSaved },
  )

  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (edit.editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [edit.editing])

  if (edit.editing) {
    return (
      <span className="description-cell" data-entry-id={entryId}>
        <input
          ref={inputRef}
          type="text"
          className="description-input"
          maxLength={500}
          value={edit.draft}
          onChange={(e) => edit.onChange(e.target.value)}
          onBlur={edit.commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              edit.commit()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              edit.cancel()
            }
          }}
        />
      </span>
    )
  }

  return (
    <span
      className="description-cell"
      data-entry-id={entryId}
      onClick={(e) => {
        e.preventDefault()
        edit.start()
      }}
    >
      {description}
    </span>
  )
}
