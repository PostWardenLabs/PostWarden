import { useEffect, useRef, useState } from 'react'

const DOW = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function pad2(n: number) {
  return String(n).padStart(2, '0')
}
function toISO(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}
function parseISO(s: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((s || '').trim())
  if (!m) return null
  const d = new Date(+m[1], +m[2] - 1, +m[3])
  return Number.isNaN(d.getTime()) ? null : d
}
function daysInMonthOf(d: Date) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
}
// Clamped, not wrapped — Jan 31 + 1 month lands on Feb 28/29, not rolling
// over into March the way `new Date(y, m+1, d)` would for a day number
// the target month doesn't have.
function addMonths(d: Date, n: number) {
  const target = new Date(d.getFullYear(), d.getMonth() + n, 1)
  target.setDate(Math.min(d.getDate(), daysInMonthOf(target)))
  return target
}

interface DatePickerProps {
  value: string
  onChange: (iso: string) => void
  disabled?: boolean
  id?: string
  name?: string
  placeholder?: string
}

// Ported from app/static/datepicker.js — a calendar popup over a plain
// text field holding (and, via onChange, committing) the exact same
// YYYY-MM-DD value a native <input type="date"> would. Typing a date
// directly still works; the calendar is the alternative, not a
// replacement.
//
// A controlled component (value/onChange), unlike legacy's DOM
// enhancement of a server-rendered <input> — the widget itself is
// otherwise a close behavioral port, including the two accessibility
// fixes that motivated it in the first place: explicit tabIndex={0} on
// every button that needs to survive Tab under macOS Safari's default
// "text fields only" Tab-order setting (see .date-day/.date-nav/
// .date-today below), and a roving-tabindex day grid so Tab doesn't have
// to walk all 28–31 day buttons one at a time to leave the calendar.
export default function DatePicker({ value, onChange, disabled, id, name, placeholder }: DatePickerProps) {
  const [open, setOpen] = useState(false)
  const [viewDate, setViewDate] = useState(() => parseISO(value) || new Date())
  const [rovingIso, setRovingIso] = useState<string | null>(null)

  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const suppressOpenOnFocus = useRef(false)
  const pendingFocusIso = useRef<string | null>(null)

  // Outside click closes the panel, same as every other popover in this
  // app (combobox, the confirm dialog's own backdrop).
  useEffect(() => {
    if (!open) return
    function onDocMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown, true)
    return () => document.removeEventListener('mousedown', onDocMouseDown, true)
  }, [open])

  // Closes on Tab (or Shift+Tab) out of the whole widget. Deliberately
  // checks document.activeElement a tick later rather than trusting
  // focusout's own relatedTarget — ported verbatim from datepicker.js's
  // own comment: arrow-key navigation below re-renders the grid and
  // refocuses the new day, destroying the *old* focused button mid-
  // render, which fires this same focusout with nothing focused for an
  // instant — reading as "focus left the widget" and closing the panel
  // out from under its own keyboard navigation if checked synchronously.
  useEffect(() => {
    if (!open) return
    const wrap = wrapRef.current
    if (!wrap) return
    function onFocusOut() {
      setTimeout(() => {
        if (wrap && !wrap.contains(document.activeElement)) setOpen(false)
      }, 0)
    }
    wrap.addEventListener('focusout', onFocusOut)
    return () => wrap.removeEventListener('focusout', onFocusOut)
  }, [open])

  // render() in datepicker.js rebuilds every .date-day button from
  // scratch on each call, so there's no node to call .focus() on until
  // after that render lands — it re-queries the DOM inline, synchronously,
  // right after building the grid. React can't do that same-tick DOM
  // query before paint, so this effect is the equivalent: focusDay()
  // below stages the target in a ref, and this runs once the grid
  // showing it has actually committed.
  useEffect(() => {
    if (!open || !pendingFocusIso.current) return
    const iso = pendingFocusIso.current
    pendingFocusIso.current = null
    panelRef.current?.querySelector<HTMLButtonElement>(`.date-day[data-iso="${iso}"]`)?.focus()
  }, [open, viewDate, rovingIso])

  function openPanel(moveFocusToGrid: boolean) {
    setViewDate(parseISO(value) || viewDate)
    setOpen(true)
    if (moveFocusToGrid) focusDay(parseISO(value) || new Date())
  }

  function closePanel(returnFocus: boolean) {
    setOpen(false)
    if (returnFocus) {
      suppressOpenOnFocus.current = true
      inputRef.current?.focus()
    }
  }

  function focusDay(d: Date) {
    setRovingIso(toISO(d))
    setViewDate(new Date(d.getFullYear(), d.getMonth(), 1))
    pendingFocusIso.current = toISO(d)
  }

  const selected = parseISO(value)
  const todayISO = toISO(new Date())
  const year = viewDate.getFullYear()
  const month = viewDate.getMonth()
  const startOffset = (new Date(year, month, 1).getDay() + 6) % 7 // Monday-first week
  const daysInMonth = daysInMonthOf(viewDate)

  const dayCells = Array.from({ length: daysInMonth }, (_, i) => {
    const day = i + 1
    return { day, iso: `${year}-${pad2(month + 1)}-${pad2(day)}` }
  })
  // Roving tabindex target, in priority order: wherever arrow-key nav
  // last left it, else the selected date, else today — falling back to
  // the 1st only if none of those land in the month actually shown.
  const preferredTarget = rovingIso || (selected && toISO(selected)) || todayISO
  const tabTarget = dayCells.some((c) => c.iso === preferredTarget) ? preferredTarget : dayCells[0]?.iso

  return (
    <div
      className="datepicker"
      ref={wrapRef}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.preventDefault()
          closePanel(true)
          return
        }
        const dayEl = (e.target as HTMLElement).closest?.('.date-day') as HTMLElement | null
        if (!dayEl) return
        const current = parseISO(dayEl.dataset.iso)
        if (!current) return
        const deltas: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
        if (e.key in deltas) {
          e.preventDefault()
          const next = new Date(current)
          next.setDate(next.getDate() + deltas[e.key])
          focusDay(next)
        } else if (e.key === 'PageUp' || e.key === 'PageDown') {
          e.preventDefault()
          focusDay(addMonths(current, e.key === 'PageUp' ? -1 : 1))
        } else if (e.key === 'Home') {
          e.preventDefault()
          focusDay(new Date(current.getFullYear(), current.getMonth(), 1))
        } else if (e.key === 'End') {
          e.preventDefault()
          focusDay(new Date(current.getFullYear(), current.getMonth(), daysInMonthOf(current)))
        }
        // Enter/Space need no handler here — they're native <button>
        // activation, which already fires each day cell's own onClick.
      }}
    >
      <input
        ref={inputRef}
        type="text"
        id={id}
        name={name}
        className="date-input"
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder || 'YYYY-MM-DD'}
        pattern="\d{4}-\d{2}-\d{2}"
        disabled={disabled}
        value={value}
        // The pattern attribute above is inert here — nothing in this app
        // calls reportValidity()/checkValidity() on this field, since it's
        // a controlled React input rather than a submitted native form
        // control, so it was never actually stopping stray characters from
        // landing in state. Filter at the source instead: only digits and
        // hyphens are ever valid in YYYY-MM-DD, and it's never longer than
        // 10 characters, so anything else (a trailing ".", pasted
        // whitespace, ...) is dropped before it reaches onChange.
        onChange={(e) => onChange(e.target.value.replace(/[^\d-]/g, '').slice(0, 10))}
        onFocus={() => {
          if (suppressOpenOnFocus.current) {
            suppressOpenOnFocus.current = false
            return
          }
          openPanel(false)
        }}
      />
      <button
        type="button"
        className="date-trigger"
        aria-label="Open calendar"
        tabIndex={0}
        disabled={disabled}
        onClick={() => (open ? closePanel(false) : openPanel(true))}
      >
        <span className="chevron chevron-down" />
      </button>
      {open && (
        <div className="date-panel" ref={panelRef}>
          <div className="date-panel-head">
            <button
              type="button"
              className="date-nav"
              tabIndex={0}
              aria-label="Previous month"
              onClick={() => setViewDate(addMonths(viewDate, -1))}
            >
              ‹
            </button>
            <span>
              {MONTHS[month]} {year}
            </span>
            <button
              type="button"
              className="date-nav"
              tabIndex={0}
              aria-label="Next month"
              onClick={() => setViewDate(addMonths(viewDate, 1))}
            >
              ›
            </button>
          </div>
          <div className="date-grid">
            {DOW.map((d) => (
              <span key={d} className="date-dow">
                {d}
              </span>
            ))}
            {Array.from({ length: startOffset }, (_, i) => (
              <span key={`pad-${i}`} />
            ))}
            {dayCells.map(({ day, iso }) => (
              <button
                key={iso}
                type="button"
                className={
                  'date-day' +
                  (selected && iso === toISO(selected) ? ' selected' : '') +
                  (iso === todayISO ? ' today' : '')
                }
                data-iso={iso}
                tabIndex={iso === tabTarget ? 0 : -1}
                onClick={() => {
                  onChange(iso)
                  closePanel(true)
                }}
              >
                {day}
              </button>
            ))}
          </div>
          <div className="date-panel-foot">
            {/* Explicit tabIndex, not just relying on a <button>'s
                default focusability — see the file-level comment above. */}
            <button
              type="button"
              className="quiet date-today"
              tabIndex={0}
              onClick={() => {
                onChange(todayISO)
                closePanel(true)
              }}
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
