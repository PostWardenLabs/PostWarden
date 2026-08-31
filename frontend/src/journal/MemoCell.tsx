import { useEffect, useRef } from 'react'

import client from '../api/client'
import { useInlineEdit } from '../widgets/useInlineEdit'

interface MemoCellProps {
  lineId: number
  memo: string | null
  onSaved: (value: string) => void
}

// Click-to-edit for a journal line's own memo, sharing `useInlineEdit`'s
// mechanics with `DescriptionCell.tsx`. Unlike the description, a memo
// *can* autosave
// blank (`allowBlank: true`) — clearing it out is a legitimate save, not
// a no-op to cancel back from.
export default function MemoCell({ lineId, memo, onSaved }: MemoCellProps) {
  const edit = useInlineEdit(
    memo || '',
    async (value) => {
      const { data, error } = await client.POST('/entries/lines/{line_id}/edit-memo', {
        params: { path: { line_id: lineId } },
        body: { memo: value },
      })
      if (error) return { ok: false }
      const body = data as unknown as { memo: string }
      return { ok: true, value: body.memo }
    },
    { allowBlank: true, onSaved },
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
      <td className="dim memo-cell" data-line-id={lineId}>
        <input
          ref={inputRef}
          type="text"
          className="memo-input"
          maxLength={200}
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
      </td>
    )
  }

  return (
    <td className="dim memo-cell" data-line-id={lineId} onClick={edit.start}>
      <span className={'memo-text' + (memo ? '' : ' memo-empty italic')}>{memo || 'Add memo'}</span>
    </td>
  )
}
