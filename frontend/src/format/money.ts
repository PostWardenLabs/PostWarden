// Ported from app/static/money-format.js's `format()`/`prefs()` (Phase
// 3.3) — the first screen with a real money figure to show. Same
// localStorage key/shape and defaults as legacy (`postwarden-number-
// format`, `{ symbol: "", position: "prefix", decimal: ".", thousands:
// "," }`), read fresh on every call rather than cached, so a change made
// on a future Settings screen (not yet built — same "don't reach into a
// screen that doesn't exist yet" reasoning every prior phase applies)
// takes effect on this page's very next render with no wiring of its own.
//
// Deliberately NOT a port of money-format.js's own *mechanism* — that
// file's `<span class="money-fmt" data-value="...">` + a DOMContentLoaded
// rewrite exists solely because Jinja renders static HTML once per page
// load and needed a way to reformat it after the fact (and to still show
// *something* correct with JS disabled). React re-renders from state on
// every change, so there's no static HTML to rewrite and no no-JS
// fallback case to cover — this is the same "port the behavior, not the
// legacy workaround for a rendering model this app no longer has" call
// `modules/auth/router.py`'s `GET /me` (Phase 1.11) already made for an
// analogous reason. Every screen just calls `formatMoney(value)` and
// renders the returned string directly.
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
// string specifically to avoid float precision loss, the same reason
// `parseFloat` here (not a plain numeric field) mirrors money-format.js's
// own `typeof value === "number" ? value : parseFloat(value)` branch,
// which existed for the identical reason (a DOM `data-value` attribute is
// always a string too).
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(n)) return ''
  const p = prefs()
  // No separate "negative zero" fix needed here the way app/main.py's own
  // `money()` filter has one (`if v == 0: v = abs(v)`) — that fix exists
  // because Python's `Decimal('-0.00')` stringifies as literally "-0.00",
  // and legacy's own %-formatting doesn't special-case it. JS's `<` and
  // `Math.abs` both already treat -0 as equal to (not less than) +0 per
  // spec, so `parseFloat("-0.00") < 0` is `false` and `Math.abs(-0)` is
  // `0` with no extra step — verified, not assumed, directly in a Node
  // REPL (no frontend test runner exists yet to carry a real unit test).
  const negative = n < 0
  const [intPart, decPart] = Math.abs(n).toFixed(2).split('.')
  const grouped = p.thousands
    ? intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ').split(' ').join(p.thousands)
    : intPart
  const number = grouped + p.decimal + decPart
  const withSymbol = p.symbol ? (p.position === 'suffix' ? number + ' ' + p.symbol : p.symbol + number) : number
  return (negative ? '-' : '') + withSymbol
}

// Trial Balance's own leaf-row cells render nothing at all for a genuine
// zero balance (`{{ r.debit_balance | money if r.debit_balance else '' }}`
// — a falsy `Decimal(0)`), not "0.00" — same rule every other point-in-
// time report will need. A plain JS truthiness check can't reproduce
// that: the value here is always a non-empty numeric *string* ("0.00"),
// which is truthy regardless of the number it spells.
export function isZeroAmount(value: string | number | null | undefined): boolean {
  if (value === null || value === undefined || value === '') return true
  const n = typeof value === 'number' ? value : parseFloat(value)
  return Number.isNaN(n) || n === 0
}
