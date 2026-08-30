import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatMoney, isZeroAmount } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import { useCollapsibleTree, type CollapsibleRow } from '../widgets/useCollapsibleTree'

// Ported from app/templates/trial_balance.html (Phase 3.3) — the first of
// Phase 3's Point-in-time report archetype, and the first screen this
// rebuild renders a real account tree or a real money figure on.
//
// GET /reports/trial-balance's own response is a plain `dict`
// (`modules/reports/router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}` — same gap `tags/TagsPage.tsx`'s own Phase
// 3.2 comment documents for GET /tags, cast through these local
// interfaces instead.
interface Row extends CollapsibleRow {
  account_code: string
  account_name: string
  path: string
  depth: number
  // `string | number`, not always `string` — confirmed with a real HTTP
  // round trip, not assumed: `domain.accounts.build_account_tree`'s own
  // `max(total, 0)`/`max(-total, 0)` (service.py) returns the *literal*
  // Python `int 0` (not a `Decimal`) whenever that bare `0` is the
  // winning side of the comparison, and `json.py`'s Decimal-to-string
  // encoder only ever runs on an actual `Decimal` instance — a plain int
  // serializes as a bare JSON number instead. `formatMoney`/
  // `isZeroAmount` (format/money.ts) already branch on `typeof value`
  // for exactly this reason (mirroring money-format.js's own identical
  // branch), so this is a type-accuracy fix, not a behavior change.
  debit_balance: string | number
  credit_balance: string | number
}

interface Group {
  type: string
  label: string
  rows: Row[]
  sub_debits: string
  sub_credits: string
  show_type_total: boolean
}

interface TrialBalanceResult {
  grouped: Group[]
  total_debits: string
  total_credits: string
  in_balance: boolean
  scenario: string
  as_of: string
  zeros: number
  raw: number
  prev_as_of: string
  next_as_of: string
  today: string
}

const COLLAPSE_KEY = 'postwarden-trial-balance-collapsed'

// Query-string state (scenario/as_of/zeros/raw), not component state —
// the direct equivalent of legacy's own `<form method="get" data-auto-
// refresh>` GET-and-redisplay design: every control change here is a
// real (if client-side, via react-router) navigation to a new URL, so
// the page stays bookmarkable/shareable/back-button-able exactly as it
// was, and the prev/next "as of" links (below) can be real `<Link>`s
// instead of onClick handlers, matching legacy's own plain `<a href>`s
// rather than approximating them with JS.
export default function TrialBalancePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<TrialBalanceResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const asOf = searchParams.get('as_of') || ''
  const zeros = searchParams.get('zeros') === '1'
  const raw = searchParams.get('raw') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/trial-balance', {
        params: { query: { scenario, as_of: asOf, zeros: zeros ? 1 : 0, raw: raw ? 1 : 0 } },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as TrialBalanceResult)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, asOf, zeros, raw])

  // Every leaf row across every group, in one flat list — what
  // useCollapsibleTree needs to walk parent chains regardless of which
  // section (Assets, Liabilities, ...) a given account sits in; the
  // synthetic earnings rows (no `id`) fall out of this the same way they
  // fall out of report-tree.js's own `tr[data-id]` selector, see that
  // hook's own docstring.
  const allRows = result ? result.grouped.flatMap((g) => g.rows) : []
  const tree = useCollapsibleTree(COLLAPSE_KEY, allRows)

  // `replace: true`, unlike the prev/next `<Link>`s below (a genuine
  // history *push*, same as clicking one of legacy's own `<a href>`s) —
  // deliberate, not a blind default. `DatePicker.tsx`'s own text field
  // fires `onChange` per keystroke, not once on blur/commit the way a
  // native `<input type="date">` fires `change`; pushing a new history
  // entry per keystroke while typing an as-of date would spam "back"
  // with a worse experience than legacy's own single-submit-per-edit
  // GET ever had, for a mid-typing state nobody actually wants to
  // navigate back into individually.
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
      {/* No help-icon here, unlike trial_balance.html's own `.page-head` —
          `/help` doesn't exist anywhere in this SPA yet (Phase 5, the
          long tail), so linking to it would be a dead link rather than a
          rough edge on an unbuilt screen. `.page-head`/`.page-sub` are
          still rendered (and their CSS still ported) since the sub-note
          itself is real content, not a placeholder for the icon. */}
      <div className="page-head">
        <p className="page-sub">
          {asOf ? `As of ${asOf}` : 'Through today'} · scenario <span className="mono">{scenario}</span>
          {!raw && ' · simulated monthly close'}
        </p>
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

      {result === null ? (
        <p>Loading…</p>
      ) : (
        <div className="report-frame">
          <p className="bar report-export">
            <a className="quiet-link" href={`/reports/trial-balance.csv?${exportQuery}`}>
              Export CSV
            </a>
            <a className="quiet-link" href={`/reports/trial-balance.xlsx?${exportQuery}`}>
              Export XLSX
            </a>
          </p>
          <table className="ledger report-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num money money-first">Debit</th>
                <th className="num money">Credit</th>
              </tr>
            </thead>
            <tbody>
              {result.grouped.map((g) => (
                <GroupRows key={g.type} group={g} tree={tree} />
              ))}
              <tr className={`grand${result.in_balance ? '' : ' out-of-balance'}`}>
                <td></td>
                <td>
                  {result.in_balance ? 'In balance' : 'Out of balance'}
                  {!result.in_balance && (
                    <span className="small dim"> (this scenario allows single-sided entries)</span>
                  )}
                </td>
                <td className="num money money-first">{formatMoney(result.total_debits)}</td>
                <td className="num money">{formatMoney(result.total_credits)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {result !== null && result.grouped.length === 0 && (
        <p className="dim">No activity in this scenario yet.</p>
      )}
    </>
  )
}

function GroupRows({ group, tree }: { group: Group; tree: ReturnType<typeof useCollapsibleTree> }) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={4}>{group.label}</td>
      </tr>
      {group.rows.map((r, i) =>
        tree.isHidden(r) ? null : (
          // Rows with no `id` (the synthetic earnings rows) fall back to
          // an index key — never reordered/added mid-list independently
          // of the rest of `group.rows`, so index is stable here, same
          // reasoning `entity-manage.js`'s own precursor never needed a
          // key at all (server-rendered, not React).
          <tr
            key={r.id ?? `${group.type}-${i}`}
            className={r.id !== undefined && r.has_children && tree.isCollapsed(r.id) ? 'collapsed' : undefined}
            data-has-children={r.id !== undefined ? (r.has_children ? '1' : '0') : undefined}
          >
            <td className="mono dim">{r.account_code}</td>
            <td
              className={`acct-name depth-${Math.min(r.depth, 6)}`}
              onClick={() => r.id !== undefined && r.has_children && tree.toggle(r.id)}
            >
              <span className="tree-toggle" />
              {r.account_name} {r.path && <span className="dim small">{r.path}</span>}
            </td>
            {/* trial_balance.html's own `entry_link()` macro branches here —
                a leaf row's non-zero balance becomes an `a.amount-link`
                drilling through to a filtered Journal. `/app/entries`
                doesn't exist yet (Phase 3.4), same "don't reach into a
                screen that doesn't exist yet" reasoning Tags' own entry-
                count column already applied (Phase 3.2) — so both of
                trial_balance.html's branches collapse into this one,
                plain-text either way, and only differ (from each other)
                in whether a balance renders at all, which `isZeroAmount`
                alone already decides. `a.amount-link`'s own CSS still
                shipped with this phase's batch regardless, ready for
                Phase 3.4 to wrap this cell in a real `<Link>`. */}
            <td className="num money money-first">{isZeroAmount(r.debit_balance) ? '' : formatMoney(r.debit_balance)}</td>
            <td className="num money">{isZeroAmount(r.credit_balance) ? '' : formatMoney(r.credit_balance)}</td>
          </tr>
        ),
      )}
      {group.show_type_total && (
        <tr className="subtotal">
          <td></td>
          <td>{group.label} subtotal</td>
          <td className="num money money-first">{formatMoney(group.sub_debits)}</td>
          <td className="num money">{formatMoney(group.sub_credits)}</td>
        </tr>
      )}
    </>
  )
}
