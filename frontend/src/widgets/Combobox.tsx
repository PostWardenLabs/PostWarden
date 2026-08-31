import { useMemo, useRef, useState } from 'react'

export interface ComboboxOption {
  value: string
  label: string
}

type ComboRow = ComboboxOption | { create: true; query: string }

// Enter on a *closed* combobox (a value's already picked, nothing left
// to commit) used to fall through to the browser's default and submit
// the enclosing form — annoying on a table full of one-combobox-per-row
// mappings (Import-with-rules' own account/category review step is the
// motivating case), where Enter reads as "the line below," not "submit."
// Tab already moves right natively; this is deliberately *not* the same
// motion — Enter only ever moves down a column, same convention
// `EntryGrid.tsx`'s own `tbody` keydown handler already established for
// the debit/credit grid (see its docstring). A combobox outside any
// `<table>` — the header-row fields above that grid, say — has no "line
// below" to speak of, so Enter there does nothing beyond the
// `preventDefault` that stops the submit; that's the actual fix, moving
// focus is only possible where a next row exists.
function focusLineBelow(current: HTMLElement) {
  const td = current.closest('td')
  const tr = td?.closest('tr')
  if (!td || !tr) return
  const cellIndex = Array.prototype.indexOf.call(tr.children, td)
  const nextTr = tr.nextElementSibling
  if (!nextTr || nextTr.tagName !== 'TR') return
  const nextTd = nextTr.children[cellIndex]
  const nextField = nextTd?.querySelector<HTMLElement>('.combobox-input, input, select, textarea')
  nextField?.focus()
}

interface ComboboxProps {
  options: ComboboxOption[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  id?: string
  name?: string
  // When present, a "+ Create <name>" row appears whenever the typed
  // text doesn't exactly match an existing option. Returning the new
  // option both selects it here *and* is this component's whole contract
  // with the caller for updating `options` — this component only ever
  // renders whatever `options` it's given, so the caller's own state
  // (wherever `options` comes from) needs to gain the new entry too, or
  // it vanishes again next render even though `value` still points at it.
  onCreate?: (name: string) => Promise<ComboboxOption | null>
}

// A searchable combobox over a plain list of options — an
// autocomplete-style text field + dropdown panel in place of a native
// <select>. A controlled component (value/onChange): there's no hidden
// native <select> at all, `value`/`onChange` are the source of truth.
//
// Two real browser-quirk fixes are encoded here: the iOS Safari
// `select()` no-op — the round-2 BACKLOG.md fix, focusing an empty field
// clears it outright instead of trying to select(), since "replace on
// next keystroke" no longer needs selection to actually take effect on
// any platform — and the general one-tick
// defer on `.select()` for a field that already holds a value, since
// select() called synchronously inside a focus handler is a known no-op
// on some WebKit builds.
export default function Combobox({ options, value, onChange, disabled, id, name, onCreate }: ComboboxProps) {
  const [open, setOpen] = useState(false)
  // What's shown in the input while open. When closed, the displayed
  // value is derived straight from `options`/`value` on every render
  // instead (see `displayValue` below) — always correct, never stale,
  // no separate "resync after every mutation" step needed.
  const [inputText, setInputText] = useState('')
  // What actually filters the panel — reset to "" whenever the panel
  // opens (always shows the unfiltered full list first; only typing
  // narrows it) and set equal to inputText on every keystroke thereafter.
  const [filterText, setFilterText] = useState('')
  const [manualActive, setManualActive] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)
  const selectTimer = useRef<number | null>(null)

  const selected = options.find((o) => o.value === value)
  const displayValue = open ? inputText : selected ? selected.label : ''

  const rows: ComboRow[] = useMemo(() => {
    const q = filterText.trim()
    const qLower = q.toLowerCase()
    let base: ComboRow[] = options.filter((o) => !qLower || o.label.toLowerCase().includes(qLower))
    if (onCreate && q) {
      const exact = options.some((o) => o.label.toLowerCase() === qLower)
      if (!exact) base = [...base, { create: true, query: q }]
    }
    return base
  }, [options, filterText, onCreate])

  // Nothing highlighted on a fresh open — this used to jump straight to
  // whichever row matched the current `value`, or, if there wasn't one
  // (a blank field), fall back to row 0 regardless. Either way, a row
  // showed up looking keyboard-selected before the user had touched
  // anything, which reads as "this is what's chosen" even though it
  // isn't — and Tab away from that state silently discarded it instead
  // of committing it, the confusing half. Only once there's an actual
  // search underway (filterText non-empty) does the first match become
  // active, so Enter still picks the top result the way typeahead is
  // expected to; arrowing down from -1 lands on row 0 same as before.
  const defaultActive = filterText.trim() === '' ? -1 : 0
  const activeIndex = manualActive !== null && manualActive < rows.length ? manualActive : defaultActive

  function openPanel() {
    setFilterText('')
    setManualActive(null)
    setCreateError(null)
    setOpen(true)
  }

  function closePanel() {
    setOpen(false)
  }

  function selectOption(opt: ComboboxOption) {
    if (opt.value !== value) onChange(opt.value)
    closePanel()
  }

  async function createAndSelect(name: string) {
    if (!onCreate) return
    setCreating(true)
    setCreateError(null)
    try {
      const opt = await onCreate(name)
      setCreating(false)
      if (!opt) {
        setCreateError("Couldn't create")
        return
      }
      onChange(opt.value)
      closePanel()
    } catch {
      setCreating(false)
      setCreateError("Couldn't reach the server")
    }
  }

  // Losing focus without an explicit pick (Tab, or clicking elsewhere)
  // resolves the same way Enter does: commit whatever's highlighted if
  // there is one (never a "+ Create" row — that only ever fires on a
  // deliberate Enter or click, not an incidental blur), clear the
  // selection outright if the field was emptied and this list actually
  // has a blank "unset" option to clear to, or just revert otherwise.
  //
  // The `manualActive === null` guard matters: arrow-key navigation
  // never touches `inputText` (only real typing does, via onChange), so
  // a field opened with nothing typed but a row picked by ArrowDown/Up
  // still has inputText === '' at this point. Gating the "field is
  // empty, clear it" branch on manualActive too — not just inputText —
  // is what lets Tab commit an arrow-key highlight instead of discarding
  // it as if the field had been left untouched.
  function resolveAndClose() {
    if (!open) return
    if (manualActive === null && inputText.trim() === '') {
      if (value !== '' && options.some((o) => o.value === '')) onChange('')
      closePanel()
    } else {
      const row = rows[activeIndex]
      if (row && !('create' in row)) selectOption(row)
      else closePanel()
    }
  }

  return (
    <div className="combobox">
      <input
        ref={inputRef}
        type="text"
        id={id}
        name={name}
        className="combobox-input"
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        disabled={disabled}
        value={displayValue}
        onFocus={() => {
          if (!value) {
            setInputText('')
          } else {
            setInputText(selected ? selected.label : '')
            if (selectTimer.current !== null) window.clearTimeout(selectTimer.current)
            selectTimer.current = window.setTimeout(() => inputRef.current?.select(), 0)
          }
          openPanel()
        }}
        onClick={() => {
          if (!open) openPanel()
        }}
        // `resolveAndClose`'s own docstring already documents "Tab, or
        // clicking elsewhere" as the two ways focus can leave without an
        // explicit pick — but only the Tab keydown branch below actually
        // called it; a plain click on something else (another field, the
        // page background) blurs the input natively with nothing wired
        // to that event at all, so the panel just stayed open, stuck
        // open until a later focus-and-pick cycle closed it (flagged
        // directly by David: "lots of combo boxes don't close when I
        // click away, they only close when I choose an option"). `onBlur`
        // fires for both cases (a real click-away, and Tab's own native
        // focus move after the keydown branch below already ran) —
        // `resolveAndClose`'s own `if (!open) return` guard makes the
        // Tab case's second call here a harmless no-op, not a double
        // resolve.
        onBlur={resolveAndClose}
        onChange={(e) => {
          setInputText(e.target.value)
          setFilterText(e.target.value)
          setManualActive(null)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            if (!open) {
              openPanel()
              return
            }
            setManualActive(Math.min(activeIndex + 1, rows.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setManualActive(Math.max(activeIndex - 1, 0))
          } else if (e.key === 'Enter') {
            const row = rows[activeIndex]
            e.preventDefault()
            if (open && row) {
              if ('create' in row) createAndSelect(row.query)
              else selectOption(row)
            } else {
              // Either already closed, or open with nothing highlighted
              // (a fresh open with an empty filter defaults `activeIndex`
              // to -1, see its own comment above) — either way there's
              // nothing to commit, so Enter just moves on. Closing first
              // matters for the open-but-unhighlighted case: leaving the
              // panel open while focus jumps to the next row read as the
              // *next* combobox spontaneously opening its own panel.
              if (open) closePanel()
              focusLineBelow(e.currentTarget)
            }
          } else if (e.key === 'Escape') {
            if (open) {
              e.preventDefault()
              closePanel()
            }
          } else if (e.key === 'Tab') {
            resolveAndClose()
          }
        }}
      />
      {open && (
        <div className="combobox-panel" role="listbox">
          {creating ? (
            <div className="combobox-empty">Creating…</div>
          ) : createError ? (
            <div className="combobox-empty combobox-error">{createError}</div>
          ) : rows.length === 0 ? (
            <div className="combobox-empty">No matches</div>
          ) : (
            rows.map((row, i) => {
              const isCreate = 'create' in row
              const label = isCreate ? `+ Create “${row.query}”` : row.label
              return (
                <div
                  key={isCreate ? `__create:${row.query}` : row.value}
                  role="option"
                  aria-selected={!isCreate && row.value === value}
                  className={
                    'combobox-option' +
                    (i === activeIndex ? ' active' : '') +
                    (!isCreate && row.value === value ? ' selected' : '') +
                    (isCreate ? ' combobox-create' : '')
                  }
                  // preventDefault so mousedown doesn't steal focus from
                  // the input mid-click.
                  onMouseDown={(e) => {
                    e.preventDefault()
                    if (isCreate) createAndSelect(row.query)
                    else selectOption(row)
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
