// Pure period-preset logic split out of PeriodPresetPicker.tsx — oxlint's
// `react(only-export-components)` flags a component file that also
// exports plain constants/functions, same fix `journal/gridLines.ts` and
// `widgets/confirmContext.ts` already applied for the identical reason.
//
// Ported from app/static/js/period-picker.js (Phase 4.1) — a convenience
// that fills in the two real date fields a range report actually submits
// (date_from/date_to); the backend only ever sees those two, never which
// preset produced them, same as legacy.
export const PERIOD_PRESETS: { value: string; label: string }[] = [
  { value: 'custom', label: 'Custom range' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'this_quarter', label: 'This quarter' },
  { value: 'last_quarter', label: 'Last quarter' },
  { value: 'this_year', label: 'This year' },
  { value: 'last_year', label: 'Last year' },
]

function iso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function monthRange(year: number, month: number): [string, string] {
  // month is 0-based; day 0 of the *next* month is the last day of this one.
  return [iso(new Date(year, month, 1)), iso(new Date(year, month + 1, 0))]
}

function quarterRange(year: number, quarterIndex0: number): [string, string] {
  const startMonth = quarterIndex0 * 3
  return [iso(new Date(year, startMonth, 1)), iso(new Date(year, startMonth + 3, 0))]
}

// Pure port of period-picker.js's own `rangeFor` switch — `today`
// defaults to `new Date()` but takes a real parameter so this stays
// testable without mocking the system clock.
export function rangeForPreset(value: string, today: Date = new Date()): [string, string] | null {
  const y = today.getFullYear()
  const m = today.getMonth()
  const q = Math.floor(m / 3)
  const todayIso = iso(today)
  switch (value) {
    case 'this_month':
      return [monthRange(y, m)[0], todayIso]
    case 'last_month':
      return monthRange(y, m - 1)
    case 'this_quarter':
      return [quarterRange(y, q)[0], todayIso]
    case 'last_quarter':
      return q === 0 ? quarterRange(y - 1, 3) : quarterRange(y, q - 1)
    case 'this_year':
      return [`${y}-01-01`, todayIso]
    case 'last_year':
      return [`${y - 1}-01-01`, `${y - 1}-12-31`]
    default:
      return null // custom — leave the fields alone
  }
}

// Reverse-match — which preset (if any) produces exactly this
// date_from/date_to pair. Mirrors legacy's own "reflect the current
// from/to back onto the dropdown on load" block, just computed at
// render time from props instead of read from the DOM once on load.
export function matchPreset(dateFrom: string, dateTo: string, today: Date = new Date()): string {
  for (const { value } of PERIOD_PRESETS) {
    if (value === 'custom') continue
    const range = rangeForPreset(value, today)
    if (range && range[0] === dateFrom && range[1] === dateTo) return value
  }
  return 'custom'
}
