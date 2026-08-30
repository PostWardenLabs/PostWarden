import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useSession } from '../auth/sessionContext'
import { centsEntryEnabled, setCentsEntryEnabled } from '../format/centsEntry'

// Ported from app/templates/settings.html (Phase 4.2, the last screen in
// this phase) — a hub of small, mostly-independent panels, not a single
// CRUD entity, so this reads differently from every other screen this
// phase built. Two of its panels are genuinely new backend-facing work
// (Account, wired to `modules/auth/router.py`'s already-existing
// `/settings/username`/`/settings/password`, split into its own
// `SettingsAccountPage.tsx` at `/app/settings/account` exactly like
// legacy's own separate `account.html`); the rest are pure client-side
// preference panels whose *mechanism* already existed before this phase
// touched anything:
//
// - **Appearance (Theme/Font)** — `index.html`'s own pre-paint `<head>`
//   script (Phase 2.4) already reads `postwarden-theme`/`postwarden-font`
//   from `localStorage` and stamps `data-theme`/`data-font` on `<html>`
//   before first paint; this panel is the first thing that ever *writes*
//   those keys. Mirrors legacy `theme.js`'s own default-is-no-attribute
//   shape (removing the key/attribute entirely at the default "slate"/
//   "system", not writing the default value).
// - **Amount entry** — `format/centsEntry.ts` (this phase), a verbatim
//   port of `cents-entry.js`'s `document`-level delegated listener,
//   already active globally (wired once in `main.tsx`) the moment this
//   phase's own commit landed; this toggle is its only UI.
// - **Number & date format** — `format/money.ts` (Phase 3.3) already
//   reads `postwarden-number-format` fresh on every `formatMoney()` call;
//   `format/date.ts` (this phase) does the same for `postwarden-date-
//   format`, now wired into the five screens legacy's own `dateformat`
//   Jinja filter actually reached (`entries.html`, `ledger.html`,
//   `cash_flow.html`, `scheduled.html`, plus `dashboard.html`/
//   `staging.html`, neither built yet). This panel is the first thing
//   that writes either key.
//
// "Connect Power BI / Excel" stays a plain, bare `<a>` to `/settings/
// connect-bi` — that screen is real backend work of its own (Phase 4.7),
// same "don't reach into a screen that doesn't exist yet" reasoning
// every prior phase's own not-yet-built link already followed.
const THEMES: { value: string; label: string }[] = [
  { value: 'slate', label: 'Slate' },
  { value: 'ledger', label: 'Ledger' },
  { value: 'midnight', label: 'Midnight' },
  { value: 'graphite', label: 'Graphite' },
  { value: 'mono', label: 'Mono' },
  { value: 'linen', label: 'Linen' },
  { value: 'budget', label: 'Budget' },
  { value: 'forest', label: 'Forest' },
  { value: 'cobalt', label: 'Cobalt' },
  { value: 'contrast', label: 'Contrast' },
  { value: 'monokai-pro', label: 'Monokai Pro' },
  { value: 'monokai-pro-light', label: 'Monokai Pro Light' },
  { value: 'one-dark', label: 'One Dark' },
  { value: 'one-light', label: 'One Light' },
  { value: 'monaspace', label: 'Monaspace' },
  { value: 'catppuccin', label: 'Catppuccin' },
  { value: 'tokyo-night', label: 'Tokyo Night' },
  { value: 'ayu', label: 'Ayu' },
  { value: 'paper', label: 'Paper' },
  { value: 'matrix', label: 'Matrix' },
  { value: 'nord', label: 'Nord' },
  { value: 'shadow', label: 'Shadow' },
]
const DEFAULT_THEME = 'slate'

const FONTS: { value: string; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'serif', label: 'Classic Serif' },
  { value: 'modern', label: 'Modern Sans' },
  { value: 'mono', label: 'Monospace' },
]
const DEFAULT_FONT = 'system'

const DATE_FORMATS: { value: string; label: string }[] = [
  { value: 'iso', label: '2026-08-26' },
  { value: 'us', label: '08/26/2026' },
  { value: 'eu', label: '26/08/2026' },
  { value: 'long', label: 'Aug 26, 2026' },
]

interface MoneyPrefs {
  symbol: string
  position: 'prefix' | 'suffix'
  decimal: string
  thousands: string
}
const MONEY_KEY = 'postwarden-number-format'
const MONEY_DEFAULTS: MoneyPrefs = { symbol: '', position: 'prefix', decimal: '.', thousands: ',' }
const DATE_KEY = 'postwarden-date-format'

function readMoneyPrefs(): MoneyPrefs {
  try {
    return { ...MONEY_DEFAULTS, ...JSON.parse(localStorage.getItem(MONEY_KEY) || '{}') }
  } catch {
    return { ...MONEY_DEFAULTS }
  }
}

export default function SettingsPage() {
  const session = useSession()

  const [theme, setTheme] = useState(() => localStorage.getItem('postwarden-theme') || DEFAULT_THEME)
  const [font, setFont] = useState(() => localStorage.getItem('postwarden-font') || DEFAULT_FONT)
  const [centsEntry, setCentsEntry] = useState(centsEntryEnabled)
  const [money, setMoney] = useState<MoneyPrefs>(readMoneyPrefs)
  const [dateFormat, setDateFormat] = useState(() => localStorage.getItem(DATE_KEY) || 'iso')

  function applyTheme(value: string) {
    setTheme(value)
    if (value === DEFAULT_THEME) {
      document.documentElement.removeAttribute('data-theme')
      localStorage.removeItem('postwarden-theme')
    } else {
      document.documentElement.setAttribute('data-theme', value)
      localStorage.setItem('postwarden-theme', value)
    }
  }

  function applyFont(value: string) {
    setFont(value)
    if (value === DEFAULT_FONT) {
      document.documentElement.removeAttribute('data-font')
      localStorage.removeItem('postwarden-font')
    } else {
      document.documentElement.setAttribute('data-font', value)
      localStorage.setItem('postwarden-font', value)
    }
  }

  function applyCentsEntry(enabled: boolean) {
    setCentsEntry(enabled)
    setCentsEntryEnabled(enabled)
  }

  function applyMoney(patch: Partial<MoneyPrefs>) {
    const next = { ...money, ...patch }
    setMoney(next)
    localStorage.setItem(MONEY_KEY, JSON.stringify(next))
  }

  function applyDateFormat(value: string) {
    setDateFormat(value)
    localStorage.setItem(DATE_KEY, value)
  }

  return (
    <>
      <p className="page-sub">
        Signed in as <strong>{session.user?.username}</strong>.
      </p>

      <div className="panel">
        <h2>Account</h2>
        <p className="dim small" style={{ marginTop: 0 }}>
          Username and password.
        </p>
        <Link className="button-link" to="/app/settings/account">
          Manage account
        </Link>
      </div>

      <div className="panel">
        <h2>Connect Power BI / Excel</h2>
        <p className="dim small" style={{ marginTop: 0 }}>
          Reporting views and a read-only database login, for connecting a BI tool straight to your
          data — no export step.
        </p>
        <a className="button-link" href="/settings/connect-bi">
          Connection details
        </a>
      </div>

      <div className="panel">
        <h2>Appearance</h2>
        <div className="bar">
          <label className="field" style={{ maxWidth: '16rem' }}>
            Theme
            <select value={theme} onChange={(e) => applyTheme(e.target.value)}>
              {THEMES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ maxWidth: '16rem' }}>
            Font
            <select value={font} onChange={(e) => applyFont(e.target.value)}>
              {FONTS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="dim small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          Font swaps the app's whole type system at once — headings, body text, and (for Classic
          Serif specifically) even the numbers in the ledger — rather than picking a single
          typeface by hand. Independent of Theme: any font works with any color theme.
        </p>
      </div>

      <div className="panel">
        <h2>Amount entry</h2>
        <label className="checkline">
          <input
            type="checkbox"
            className="switch"
            checked={centsEntry}
            onChange={(e) => applyCentsEntry(e.target.checked)}
          />
          Fill amounts right-to-left, like a bank transfer app
        </label>
        <p className="dim small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          When on, typing digits into a Debit or Credit field fills in from the cents up — no
          decimal point to type. <span className="mono">62</span> types as{' '}
          <span className="mono">00.62</span>; keep typing <span className="mono">6200</span> to
          reach <span className="mono">62.00</span>.
        </p>
      </div>

      <div className="panel">
        <h2>Number &amp; date format</h2>
        <div className="bar">
          <label className="field" style={{ maxWidth: '8rem' }}>
            Symbol
            <input
              type="text"
              placeholder="e.g. $"
              maxLength={6}
              value={money.symbol}
              onChange={(e) => applyMoney({ symbol: e.target.value })}
            />
          </label>
          <label className="field" style={{ maxWidth: '9rem' }}>
            Position
            <select
              value={money.position}
              onChange={(e) => applyMoney({ position: e.target.value as MoneyPrefs['position'] })}
            >
              <option value="prefix">Before ($1)</option>
              <option value="suffix">After (1$)</option>
            </select>
          </label>
          <label className="field" style={{ maxWidth: '9rem' }}>
            Decimal mark
            <select value={money.decimal} onChange={(e) => applyMoney({ decimal: e.target.value })}>
              <option value=".">Period (1.50)</option>
              <option value=",">Comma (1,50)</option>
            </select>
          </label>
          <label className="field" style={{ maxWidth: '10rem' }}>
            Thousands mark
            <select value={money.thousands} onChange={(e) => applyMoney({ thousands: e.target.value })}>
              <option value=",">Comma (1,000)</option>
              <option value=".">Period (1.000)</option>
              <option value=" ">Space (1 000)</option>
              <option value="">None (1000)</option>
            </select>
          </label>
          <label className="field" style={{ maxWidth: '11rem' }}>
            Date format
            <select value={dateFormat} onChange={(e) => applyDateFormat(e.target.value)}>
              {DATE_FORMATS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="dim small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          Changes how amounts and dates are displayed everywhere — Journal, Scheduled entries,
          Ledger, Cash Flow. Leave Symbol blank for plain numbers. This never changes what's
          stored; it's purely how it's shown to you, in this browser.
        </p>
      </div>
    </>
  )
}
