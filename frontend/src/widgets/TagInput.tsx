import { useMemo, useRef, useState } from 'react'

const TAG_PATTERN = /^[a-z0-9][a-z0-9 _-]{0,39}$/

type Row = string | { create: true; query: string }

interface TagInputProps {
  // Comma-separated, matching every server-side consumer's own shape
  // (`CreateEntryRequest.tags`, `EditTagsRequest.tag`, the Journal
  // filter bar's own `tags` query param) — a caller never needs to
  // convert to/from an array itself.
  value: string
  onChange: (csv: string) => void
  suggestions: string[]
  // The Journal filter bar's own Tags field sets this false, since
  // filtering by a tag that doesn't exist yet is meaningless (there's
  // nothing it could ever match).
  creatable?: boolean
  placeholder?: string
  id?: string
}

// A chip-based tag picker: typing filters existing tags (arrow keys move
// a highlighted row, same as Combobox.tsx), and only actually selecting
// one (click, Enter, or a trailing comma) adds it. A tag that doesn't
// exist yet shows as a "+ Create tag "…"" row, same affordance
// Combobox.tsx's own `onCreate` gives a single-value field — but there's
// nothing to await here: a new tag is only ever created for real,
// lazily, wherever the *form* submits it (`domain.entry.parse_tags`/
// `repository.sync_entry_tags` upsert by name), so this component just
// adds it to the chip list client-side rather than round-tripping to
// `POST /tags` on every keystroke — nothing to roll back if the form is
// abandoned.
//
// A controlled component (value/onChange) — no server-rendered fallback
// markup to preserve underneath it on an SPA.
export default function TagInput({ value, onChange, suggestions, creatable = true, placeholder, id }: TagInputProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const tags = useMemo(() => value.split(',').map((s) => s.trim()).filter(Boolean), [value])

  const { rows, invalidReason } = useMemo(() => {
    const q = query.trim().toLowerCase()
    let base: Row[] = suggestions.filter((s) => !tags.includes(s) && (!q || s.includes(q)))
    const exact = suggestions.some((s) => s === q)
    let reason: string | null = null
    if (creatable && q && !exact && !tags.includes(q)) {
      if (TAG_PATTERN.test(q)) {
        base = [...base, { create: true, query: q }]
      } else {
        reason = 'Only lowercase letters, numbers, spaces, - and _, max 40 chars'
      }
    }
    return { rows: base, invalidReason: reason }
  }, [suggestions, tags, query, creatable])

  function openPanel() {
    setActiveIndex(0)
    setOpen(true)
  }

  function closePanel() {
    setOpen(false)
  }

  function addTag(name: string) {
    setQuery('')
    closePanel()
    if (!name || tags.includes(name)) return
    onChange([...tags, name].join(','))
  }

  function removeTag(name: string) {
    onChange(tags.filter((t) => t !== name).join(','))
  }

  function selectActive() {
    const row = rows[activeIndex]
    if (!row) return
    addTag(typeof row === 'string' ? row : row.query)
  }

  return (
    <div className="tag-input" ref={rootRef}>
      {tags.map((t) => (
        <span className="tag-chip" key={t}>
          {t}
          <button
            type="button"
            className="tag-chip-remove"
            aria-label={`Remove tag ${t}`}
            onClick={() => removeTag(t)}
          >
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        id={id}
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-expanded={open}
        placeholder={placeholder || 'Add a tag…'}
        value={query}
        onFocus={openPanel}
        onChange={(e) => {
          setQuery(e.target.value)
          setActiveIndex(0)
          setOpen(true)
        }}
        onBlur={() => {
          // A tick later, same reasoning DatePicker.tsx's own
          // outside-interaction checks use — closing synchronously on
          // blur would fire before a panel-row mousedown's own
          // preventDefault has a chance to matter, and before this
          // component's own outside-click listener (there isn't one;
          // blur already covers it) would otherwise need to.
          window.setTimeout(closePanel, 0)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            if (!open) {
              openPanel()
              return
            }
            setActiveIndex((i) => Math.min(i + 1, rows.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActiveIndex((i) => Math.max(i - 1, 0))
          } else if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            if (open) selectActive()
          } else if (e.key === 'Backspace' && !query && tags.length) {
            onChange(tags.slice(0, -1).join(','))
          } else if (e.key === 'Escape' && open) {
            e.preventDefault()
            closePanel()
          }
        }}
      />
      {open && (
        <div className="combobox-panel" role="listbox">
          {rows.length === 0 ? (
            <div className={'combobox-empty' + (invalidReason ? ' combobox-error' : '')}>
              {invalidReason || 'No matches'}
            </div>
          ) : (
            rows.map((row, i) => {
              const isCreate = typeof row !== 'string'
              const label = isCreate ? `+ Create tag “${row.query}”` : row
              return (
                <div
                  key={isCreate ? `__create:${row.query}` : row}
                  role="option"
                  aria-selected={!isCreate}
                  className={'combobox-option' + (i === activeIndex ? ' active' : '') + (isCreate ? ' combobox-create' : '')}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    addTag(isCreate ? row.query : row)
                  }}
                >
                  {label}
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
