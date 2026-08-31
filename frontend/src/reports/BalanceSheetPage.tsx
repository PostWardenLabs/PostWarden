import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import { useCollapsibleTree, type CollapsibleRow } from '../widgets/useCollapsibleTree'

// Ported from app/templates/balance_sheet.html (Phase 4.1) — the second
// Point-in-time report screen, built directly on TrialBalancePage.tsx's
// own pattern (Phase 3.3): URL-state filters, one useEffect fetch, a
// useCollapsibleTree'd account tree. The one structural difference from
// Trial Balance worth calling out: `GET /reports/balance-sheet`'s own
// response is NOT the `{grouped: [...]}` per-type-section shape Trial
// Balance returns — `service.balance_sheet` flattens straight to three
// separate top-level arrays (`assets`/`liabilities`/`equity`), each
// already a flatten_tree() row list with no section wrapper.
//
// There used to be a fourth field here, `earnings_lines` — a flat list
// of plain `[label, amount]` tuples rendered in its own separate `.map`
// below `equity`, bypassing `tree` entirely. It's gone: the "Retained
// Earnings" figure is a real collapsible tree node now (see
// `domain.accounts.earnings_rows`'s own docstring), appended straight
// onto `result["equity"]` server-side, so it renders through the exact
// same `SectionRows` component every real Equity account already does —
// no separate render path needed here at all.
interface Row extends CollapsibleRow {
  account_code: string
  account_name: string
  path: string
  depth: number
  // See TrialBalancePage.tsx's own comment on why this is `string |
  // number`, not always `string` — the same `max(total, 0)`-shaped
  // literal-int gap applies here too (`domain/accounts.py`'s
  // `build_account_tree`'s `debit_balance`/`credit_balance`, unused by
  // this page, but `subtotal` itself can be a bare `Decimal(0)` for an
  // account with no activity, which still serializes as a proper
  // Decimal string — the `string | number` widening here is precautionary
  // parity with every other report's row type, not a second confirmed gap).
  subtotal: string | number
}

interface BalanceSheetResult {
  assets: Row[]
  liabilities: Row[]
  equity: Row[]
  total_assets: string
  total_liabilities: string
  total_equity: string
  total_liab_and_equity: string
  in_balance: boolean
  scenario: string
  as_of: string
  zeros: number
  raw: number
  prev_as_of: string
  next_as_of: string
  today: string
}

const COLLAPSE_KEY = 'postwarden-balance-sheet-collapsed'

export default function BalanceSheetPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<BalanceSheetResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const asOf = searchParams.get('as_of') || ''
  const zeros = searchParams.get('zeros') === '1'
  const raw = searchParams.get('raw') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/balance-sheet', {
        params: { query: { scenario, as_of: asOf, zeros: zeros ? 1 : 0, raw: raw ? 1 : 0 } },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as BalanceSheetResult)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, asOf, zeros, raw])

  // One tree across all three sections — same reasoning TrialBalancePage
  // gives: useCollapsibleTree only needs a flat list to walk parent
  // chains, it doesn't care which section a row's in. `result.equity`
  // already includes the synthetic "Retained Earnings" node (a real
  // parent/children triple now, not id-less tuples), so it's registered
  // with the tree exactly like every real Equity account is — no
  // separate handling needed.
  const allRows = result ? [...result.assets, ...result.liabilities, ...result.equity] : []
  const tree = useCollapsibleTree(COLLAPSE_KEY, allRows)

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  function pageParams(overrides: Record<string, string>): string {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(overrides)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    return next.toString()
  }

  const exportQuery = `scenario=${encodeURIComponent(scenario)}&as_of=${encodeURIComponent(asOf)}&zeros=${zeros ? 1 : 0}&raw=${raw ? 1 : 0}`

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          As of {asOf || 'today'} · scenario <span className="mono">{scenario}</span>
          {!raw && ' · simulated monthly close'}
        </p>
        <Link to="/app/help#reports" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      <div className="bar">
        <label className="field">
          Scenario
          <Combobox
            options={(scenarios ?? []).map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
            value={scenario}
            onChange={(v) => setParam('scenario', v)}
          />
        </label>
        <label className="field">
          As of
          <DatePicker value={asOf} onChange={(v) => setParam('as_of', v)} />
        </label>
      </div>

      {result && (
        <p className="bar" style={{ alignItems: 'center' }}>
          <Link className="quiet-link" to={`?${pageParams({ as_of: result.prev_as_of })}`}>
            &larr; {result.prev_as_of.slice(0, 7)}
          </Link>
          <Link className="quiet-link" to={`?${pageParams({ as_of: result.next_as_of })}`}>
            {result.next_as_of.slice(0, 7)} &rarr;
          </Link>
        </p>
      )}

      <p className="bar" style={{ alignItems: 'center' }}>
        <label className="checkline">
          <input type="checkbox" checked={zeros} onChange={(e) => setParam('zeros', e.target.checked ? '1' : '')} />
          show zero balances
        </label>
        <label className="checkline">
          <input type="checkbox" checked={raw} onChange={(e) => setParam('raw', e.target.checked ? '1' : '')} />
          show true balances (skip simulated close)
        </label>
      </p>

      {/* Unlike Trial Balance's own raw=1, there's no Income/Expense
          section here for the unclosed P&L to relocate into — so raw=1
          means the "Retained Earnings" line is just gone, not merged
          into one line the way an earlier version of this page did.
          That's not a bug: SPEC.md decision 10's own addendum on this
          is explicit that a balance sheet genuinely doesn't reconcile
          against Assets alone before a real close, and PostWarden never
          performs one. Said up front, not just implied by the grand
          total row quietly turning red below. */}
      {raw && (
        <p className="dim small">
          *Balance sheet won't balance pre-close — Assets already reflect this year's activity, Equity won't
          until you close.
        </p>
      )}

      {result === null ? (
        <p>Loading…</p>
      ) : (
        <div className="report-frame">
          <p className="bar report-export">
            <a className="quiet-link" href={`/reports/balance-sheet.csv?${exportQuery}`}>
              Export CSV
            </a>
            <a className="quiet-link" href={`/reports/balance-sheet.xlsx?${exportQuery}`}>
              Export XLSX
            </a>
          </p>
          <table className="ledger report-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num money money-first">Amount</th>
              </tr>
            </thead>
            <tbody>
              <SectionRows label="Assets" rows={result.assets} tree={tree} sign={1}
                           scenario={scenario} asOf={result.as_of} />
              <tr className="subtotal">
                <td></td>
                <td>Total assets</td>
                <td className="num money money-first">{formatMoneyOrDash(result.total_assets)}</td>
              </tr>

              <SectionRows label="Liabilities" rows={result.liabilities} tree={tree} sign={-1}
                           scenario={scenario} asOf={result.as_of} />
              <tr className="subtotal">
                <td></td>
                <td>Total liabilities</td>
                <td className="num money money-first">{formatMoneyOrDash(result.total_liabilities)}</td>
              </tr>

              <SectionRows label="Equity" rows={result.equity} tree={tree} sign={-1}
                           scenario={scenario} asOf={result.as_of} />
              <tr className="subtotal">
                <td></td>
                <td>Total equity</td>
                <td className="num money money-first">{formatMoneyOrDash(result.total_equity)}</td>
              </tr>

              <tr className={`grand${result.in_balance ? '' : ' out-of-balance'}`}>
                <td></td>
                <td>
                  Total liabilities + equity
                  {!result.in_balance && (
                    <span className="small dim">
                      {raw ? ' (expected — see note above)' : " (doesn't match total assets)"}
                    </span>
                  )}
                </td>
                <td className="num money money-first">{formatMoneyOrDash(result.total_liab_and_equity)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// `sign` flips liabilities/equity's stored subtotal (credit-normal,
// negative internally) to display as a positive figure — the exact
// negation `balance_sheet.html`'s own `entry_link(r.account_code,
// -r.subtotal)` applies for every non-Assets row, ported here as a
// per-section multiplier rather than repeating the ternary three times.
function SectionRows({
  label,
  rows,
  tree,
  sign,
  scenario,
  asOf,
}: {
  label: string
  rows: Row[]
  tree: ReturnType<typeof useCollapsibleTree>
  sign: 1 | -1
  scenario: string
  asOf: string
}) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={3}>{label}</td>
      </tr>
      {rows.map((r) =>
        tree.isHidden(r) ? null : (
          <tr
            key={r.id}
            className={r.has_children && r.id !== undefined && tree.isCollapsed(r.id) ? 'collapsed' : undefined}
            data-has-children={r.has_children ? '1' : '0'}
          >
            <td className="mono dim">{r.account_code}</td>
            <td
              className={`acct-name depth-${Math.min(r.depth, 6)}`}
              onClick={() => r.id !== undefined && r.has_children && tree.toggle(r.id)}
            >
              <span className="tree-toggle" />
              {r.account_name} {r.path && <span className="dim small">{r.path}</span>}
            </td>
            <td className="num money money-first">
              {/* balance_sheet.html's own entry_link(r.account_code,
                  -r.subtotal) if not r.has_children else plain text —
                  every leaf drills through regardless of amount (unlike
                  Trial Balance, which only links a non-zero balance);
                  a summary/parent row stays plain text either way. No
                  date_from: a balance-sheet account is always cumulative
                  through as_of, never bounded to a period. */}
              {r.has_children ? (
                formatMoneyOrDash(Number(r.subtotal) * sign)
              ) : (
                <Link className="amount-link"
                      to={`/app/entries?scenario=${encodeURIComponent(scenario)}&date_to=${asOf}&account=${encodeURIComponent(r.account_code)}`}>
                  {formatMoneyOrDash(Number(r.subtotal) * sign)}
                </Link>
              )}
            </td>
          </tr>
        ),
      )}
    </>
  )
}
