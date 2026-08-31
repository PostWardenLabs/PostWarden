// Reads the user's preferred number format from localStorage (set from
// SettingsPage.tsx: `postwarden-number-format`, `{ symbol: "", position:
// "prefix", decimal: ".", thousands: "," }`), fresh on every call rather
// than cached, so a change made on Settings takes effect on the next
// render with no wiring of its own. Every screen just calls
// `formatMoney(value)` and renders the returned string directly.
const STORAGE_KEY = 'postwarden-number-format'

interface MoneyPrefs {
  symbol: string
  position: 'prefix' | 'suffix'
  decimal: string
  thousands: string
}

const DEFAULTS: MoneyPrefs = { symbol: '', position: 'prefix', decimal: '.', thousands: ',' }

function prefs(): MoneyPrefs {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }
  } catch {
    return { ...DEFAULTS }
  }
}

// `value` arrives as a JSON string, not a number — `json.py`'s own
// Decimal encoder (backend) serializes every `NUMERIC(18,2)` figure as a
// string specifically to avoid float precision loss, which is why this
// branches on `typeof value` instead of assuming a plain numeric field.
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(n)) return ''
  const p = prefs()
  // No separate "negative zero" fix needed here — Python's own
  // `Decimal('-0.00')` stringifies as literally "-0.00" (see
  // `domain/money.py`'s `normalize_zero`, which corrects it server-side
  // before this ever runs), but JS's `<` and `Math.abs` both already
  // treat -0 as equal to (not less than) +0 per spec, so
  // `parseFloat("-0.00") < 0` is `false` and `Math.abs(-0)` is `0` with
  // no extra step — verified, not assumed, directly in a Node REPL (no
  // frontend test runner exists yet to carry a real unit test).
  const negative = n < 0
  const [intPart, decPart] = Math.abs(n).toFixed(2).split('.')
  const grouped = p.thousands
    ? intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ').split(' ').join(p.thousands)
    : intPart
  const number = grouped + p.decimal + decPart
  const withSymbol = p.symbol ? (p.position === 'suffix' ? number + ' ' + p.symbol : p.symbol + number) : number
  return (negative ? '-' : '') + withSymbol
}

// Trial Balance's own debit/credit leaf-row cells render nothing at all
// for a genuine zero balance, not "0.00" — a plain JS truthiness check
// can't do this on its own: the value here is always a non-empty numeric
// *string* ("0.00"), which is truthy regardless of the number it spells.
// Used for exactly that one case — a debit/credit *pair*, where one side
// is trivially $0 for nearly every row by construction (a balance can't
// be on both sides at once), so a blank non-balance side is the
// meaningful signal, not noise. `formatMoneyOrDash` below is the one
// every single-value money column should reach for instead.
export function isZeroAmount(value: string | number | null | undefined): boolean {
  if (value === null || value === undefined || value === '') return true
  const n = typeof value === 'number' ? value : parseFloat(value)
  return Number.isNaN(n) || n === 0
}

// A genuine $0 in a single-value money column (as opposed to one side of
// a debit/credit pair — see `isZeroAmount`'s own comment on why those
// stay blank instead) renders as "—", the same em dash `ScenariosPage
// .tsx`/`EntryTemplatesPage.tsx`/`ScheduledPage.tsx` already use for "no
// value here" elsewhere in the app, not "0.00" and not blank. Missing
// data (`null`/`undefined`/`''`) is a different case from a real zero
// and stays blank, same as `formatMoney` itself already does for it —
// this only ever changes what a *present*, genuinely-zero value shows.
export function formatMoneyOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(n)) return ''
  return n === 0 ? '—' : formatMoney(value)
}
