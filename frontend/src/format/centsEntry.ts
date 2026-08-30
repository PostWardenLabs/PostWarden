// Ported from app/static/cents-entry.js (Phase 4.2) — the optional
// "digits fill in from the right" mode for amount fields (EntryGrid.tsx's
// debit/credit `<input className="amount">`), same input style as a bank
// transfer app: typing 6200 produces 62.00, no decimal point to type.
// Off by default, toggled from SettingsPage.tsx.
//
// A genuine verbatim port of the *mechanism*, not just the behavior —
// unlike `format/date.ts`/`format/money.ts` (which replace a legacy
// DOM-rewrite with a plain function every screen calls), this one is
// already exactly the right shape for React: legacy's own file is a
// `document`-level delegated listener matching `input.amount` by
// className, needing no knowledge of which page or which row added the
// field. `EntryGrid.tsx`'s debit/credit inputs already carry that same
// `amount` className (ported in Phase 3.4, before this file existed) —
// so this needs no EntryGrid changes at all, and covers Journal/
// Scheduled/Entry templates' grids for free the moment it's initialized
// once, same as legacy's own global `<script>` include covered every
// page for free.
//
// `initCentsEntry()` is called once from `main.tsx`, outside React
// entirely — nothing here is a React concern (no component owns these
// listeners, no state to re-render on), the same reasoning the pre-paint
// theme/font script in `index.html` already applies to itself.
const KEY = 'postwarden-cents-entry'

export function centsEntryEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setCentsEntryEnabled(enabled: boolean): void {
  if (enabled) localStorage.setItem(KEY, '1')
  else localStorage.removeItem(KEY)
}

function isAmountField(el: EventTarget | null): el is HTMLInputElement {
  return !!el && el instanceof HTMLInputElement && el.classList.contains('amount')
}

function parseCents(value: string): number {
  const n = parseFloat(value)
  return Number.isNaN(n) ? 0 : Math.round(n * 100)
}

// React DOM installs a value tracker on every <input> instance (see
// react-dom's inputValueTracking.js) so its change-event plugin can tell
// a real change from a no-op before invoking a controlled component's
// onChange. A plain `field.value = x` goes through that same
// instance-level setter, which updates the tracker's recorded value
// *before* the subsequent `dispatchEvent` runs — so by the time React's
// plugin compares "new value" against "tracked value" they already
// match, and onChange never fires. EntryGrid's debit/credit totals are
// derived from React state, so this isn't cosmetic: the field visibly
// showed "62.00" while the totals bar stayed stuck at a stale value
// from before this function ran (caught in manual verification, not by
// oxlint/tsc — neither flags this). The standard workaround is calling
// the *prototype's* setter directly, bypassing the instance override
// React installed, so the tracker still sees the old value at
// comparison time and correctly detects the change.
const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set

function setFromCents(field: HTMLInputElement, cents: number): void {
  const clamped = Math.max(0, Math.min(cents, 99999999999)) // a sane ceiling, not a real limit
  const value = (clamped / 100).toFixed(2)
  if (nativeInputValueSetter) nativeInputValueSetter.call(field, value)
  else field.value = value
  field.dispatchEvent(new Event('input', { bubbles: true }))
}

let initialized = false

export function initCentsEntry(): void {
  if (initialized) return // StrictMode double-invokes effects; listeners must attach once
  initialized = true

  // A fresh focus always starts a fresh number — the first digit typed
  // after focusing (or re-focusing) a field replaces whatever was there
  // rather than shifting on top of it, same as tapping an amount field
  // in a banking app. Only digits typed *after* that first one keep
  // shifting left within this same focus session.
  document.addEventListener(
    'focus',
    (e) => {
      if (!centsEntryEnabled() || !isAmountField(e.target)) return
      delete e.target.dataset.centsStarted
    },
    true,
  )

  document.addEventListener('keydown', (e) => {
    if (!centsEntryEnabled() || !isAmountField(e.target)) return
    const field = e.target
    if (/^[0-9]$/.test(e.key)) {
      e.preventDefault()
      const cents =
        field.dataset.centsStarted === '1' ? parseCents(field.value) * 10 + Number(e.key) : Number(e.key)
      field.dataset.centsStarted = '1'
      setFromCents(field, cents)
    } else if (e.key === 'Backspace') {
      e.preventDefault()
      field.dataset.centsStarted = '1'
      setFromCents(field, Math.floor(parseCents(field.value) / 10))
    } else if (e.key.length > 1) {
      // Tab / arrows / Enter / Escape / etc. — navigation and control
      // keys pass through untouched; the next digit still replaces.
      delete field.dataset.centsStarted
    } else {
      // Anything else typeable (a literal ".", letters, ...) is exactly
      // what this mode exists to make unnecessary — block it rather
      // than let it desync the field from the digit buffer.
      e.preventDefault()
    }
  })
}
