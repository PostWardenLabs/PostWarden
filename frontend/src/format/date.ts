// Reads the user's preferred date format from localStorage (set from
// SettingsPage.tsx), fresh on every call rather than cached — mirroring
// `format/money.ts`'s own identical contract for the identical reason (a
// change made on Settings takes effect on the next render with no wiring
// of its own). React re-renders from state, so every date-displaying
// screen just calls `formatDate(iso)` directly and renders the returned
// string.
//
// Parses the ISO string by hand rather than `new Date("2026-08-26")` —
// that parses as UTC midnight, which local-timezone display would then
// render as the *previous* day west of UTC. Every date column in this
// app is a plain `DATE` (no time, no timezone), so this only ever needs
// to reorder y/m/d, never a real timezone conversion.
const STORAGE_KEY = 'postwarden-date-format'
const DEFAULT_FORMAT = 'iso'
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

function pref(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_FORMAT
  } catch {
    return DEFAULT_FORMAT
  }
}

export function formatDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '')
  if (!m) return iso || ''
  const [, y, mo, d] = m
  const moNum = parseInt(mo, 10)
  switch (pref()) {
    case 'us':
      return `${mo}/${d}/${y}`
    case 'eu':
      return `${d}/${mo}/${y}`
    case 'long':
      return `${MONTHS[moNum - 1]} ${parseInt(d, 10)}, ${y}`
    case 'iso':
    default:
      return `${y}-${mo}-${d}`
  }
}
