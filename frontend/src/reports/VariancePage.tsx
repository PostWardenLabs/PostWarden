import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useAccountLevels } from '../api/useAccountLevels'
import { useScenarios } from '../api/useScenarios'
import { formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import { useCollapsibleTree, type CollapsibleRow } from '../widgets/useCollapsibleTree'

// A Point-in-time report (Balance Sheet/Variance/Ledger, per
// UI_CONSISTENCY_AUDIT.md §2c's reclassification), and the only one with
// a genuinely different row shape depending on the request: native-depth
// (a real account tree, same flatten_tree() shape Trial Balance/Balance
// Sheet use) vs. rolled-up (a flat SQL-side aggregation with no id/
// parent_id/depth at all — confirmed by reading `service.compute_
// variance` directly). `result.rolled_up` discriminates the two.
//
// variance.html's own row markup already handles both shapes uniformly
// by checking `r.id is defined` — no id means no tree-toggle, no depth
// class, no data-id — which is exactly what `useCollapsibleTree` already
// does for an id-less row for free (never registered, so `isHidden`
// never hides it and `toggle` never applies to it). So, like Balance
// Sheet/Trial Balance, this page always runs every row through the same
// `useCollapsibleTree` call — no separate branch needed for rolled-up
// mode, it degrades to "nothing is ever collapsible" on its own.
interface Row extends CollapsibleRow {
  account_code: string
  account_name: string
  path?: string
  depth?: number
  baseline_net: string | number
  compare_net: string | number
  variance: string | number
  pct_variance: string | null
}

interface Group {
  type: string
  label: string
  rows: Row[]
  sub_baseline: string | number
  sub_compare: string | number
  sub_variance: string | number
  sub_pct_variance: string | null
}

interface VarianceResult {
  grouped: Group[]
  rolled_up: boolean
  compare: string
  level_id: string
  total_baseline: string
  total_compare: string
  total_variance: string
  total_pct_variance: string | null
  baseline: string
  as_of: string
  zeros: number
  pct_of_base: number
  prev_as_of: string
  next_as_of: string
  today: string
}

const COLLAPSE_KEY = 'postwarden-variance-collapsed'

// `var()` in variance.html/income_statement.html — a bare Decimal string
// printed as-is, red only when negative.
function pctText(pct: string | null) {
  if (pct === null) return <span className="dim">—</span>
  return <span className={Number(pct) < 0 ? 'neg' : undefined}>{pct}%</span>
}

export default function VariancePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const levels = useAccountLevels()
  const [result, setResult] = useState<VarianceResult | null>(null)

  const baseline = searchParams.get('baseline') || 'ACTUAL'
  // compare/level_id can be server-resolved even when the URL leaves them
  // blank (service.compute_variance auto-picks a compare scenario, and
  // defaults level_id from that scenario's own base level) — once a
  // result exists, its own resolved values are what the pickers should
  // show, not a blank URL param a fetch already moved past. The fetch
  // itself still keys off the raw URL value, same as every other field.
  const urlCompare = searchParams.get('compare') || ''
  const urlLevelId = searchParams.get('level_id') || ''
  const compare = result ? result.compare : urlCompare
  const levelId = result ? result.level_id : urlLevelId
  const asOf = searchParams.get('as_of') || ''
  const zeros = searchParams.get('zeros') === '1'
  const pctOfBase = searchParams.get('pct_of_base') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/variance', {
        params: {
          query: {
            baseline,
            compare: urlCompare,
            level_id: urlLevelId,
            as_of: asOf,
            zeros: zeros ? 1 : 0,
            pct_of_base: pctOfBase ? 1 : 0,
          },
        },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as VarianceResult)
      })
    return () => {
      cancelled = true
    }
  }, [baseline, urlCompare, urlLevelId, asOf, zeros, pctOfBase])

  const allRows = result ? result.grouped.flatMap((g) => g.rows) : []
  const tree = useCollapsibleTree(COLLAPSE_KEY, allRows)

  // Same "never posted to" vs. "nothing in this window" split as
  // TrialBalancePage.tsx, but checked against both scenarios in the pair
  // — treated as one combined condition (not per-scenario), matching how
  // the rest of this report already treats baseline/compare as a unit
  // rather than reporting on each separately.
  const baselineRow = (scenarios ?? []).find((s) => s.code === baseline)
  const compareRow = (scenarios ?? []).find((s) => s.code === compare)
  const neitherHasEntries =
    !!baselineRow && !!compareRow && baselineRow.entry_count === 0 && compareRow.entry_count === 0

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

  const exportQuery =
    `baseline=${encodeURIComponent(baseline)}&compare=${encodeURIComponent(compare)}` +
    `&level_id=${encodeURIComponent(levelId)}&as_of=${encodeURIComponent(asOf)}` +
    `&zeros=${zeros ? 1 : 0}&pct_of_base=${pctOfBase ? 1 : 0}`

  return (
    <>
      {/* variance.html's own .page-head holds nothing but the help-icon
          (no .page-sub at all, unlike every other report). */}
      <div className="page-head">
        <Link to="/app/help#variance" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      <div className="bar">
        <label className="field">
          Scenario
          <Combobox
            options={(scenarios ?? []).map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
            value={baseline}
            onChange={(v) => setParam('baseline', v)}
          />
        </label>
        <label className="field">
          Compare to
          <Combobox
            options={(scenarios ?? []).map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
            value={compare}
            onChange={(v) => setParam('compare', v)}
          />
        </label>
        <label className="field">
          Roll up to
          <Combobox
            options={[
              { value: '', label: 'No rollup (native depth)' },
              ...(levels ?? []).map((l) => ({ value: String(l.id), label: l.name })),
            ]}
            value={levelId}
            onChange={(v) => setParam('level_id', v)}
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
        <label
          className="checkline"
          title={
            result?.rolled_up
              ? 'Only applies at native depth — a rolled-up row already represents whatever was pooled into it, with no zero-balance rows left to reveal underneath.'
              : undefined
          }
        >
          <input type="checkbox" checked={zeros} onChange={(e) => setParam('zeros', e.target.checked ? '1' : '')} />
          show zero balances
        </label>
        <label
          className="checkline"
          title="Default: Baseline − Compare, as a % of Compare. Checked: Compare − Baseline, as a % of Baseline."
        >
          <input
            type="checkbox"
            checked={pctOfBase}
            onChange={(e) => setParam('pct_of_base', e.target.checked ? '1' : '')}
          />
          Flip variance direction
        </label>
      </p>

      {result === null ? (
        <p>Loading…</p>
      ) : (
        <div className="report-frame">
          <p className="bar report-export">
            <a className="quiet-link" href={`/reports/variance.csv?${exportQuery}`}>
              Export CSV
            </a>
            <a className="quiet-link" href={`/reports/variance.xlsx?${exportQuery}`}>
              Export XLSX
            </a>
          </p>
          <table className="ledger report-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num money money-first">{baseline}</th>
                <th className="num money">Variance</th>
                <th className="num">% variance</th>
                <th className="num money">{compare}</th>
              </tr>
            </thead>
            <tbody>
              {result.grouped.map((g) => (
                <GroupRows key={g.type} group={g} tree={tree} />
              ))}
              <tr className="grand">
                <td></td>
                <td>Total</td>
                <td className="num money money-first">{formatMoneyOrDash(result.total_baseline)}</td>
                <td className={`num money ${Number(result.total_variance) < 0 ? 'neg' : ''}`}>
                  {formatMoneyOrDash(result.total_variance)}
                </td>
                <td className="num">{pctText(result.total_pct_variance)}</td>
                <td className="num money">{formatMoneyOrDash(result.total_compare)}</td>
              </tr>
            </tbody>
          </table>
          {result.grouped.length === 0 && (
            <p className="dim">
              {neitherHasEntries ? (
                <>
                  Neither scenario has any entries yet. Post one from{' '}
                  <Link className="quiet-link" to="/app/entries?new=1">
                    + New entry
                  </Link>
                  .
                </>
              ) : (
                <>No activity in either scenario as of {asOf || 'today'}. Try an earlier — or blank — "as of" date.</>
              )}
            </p>
          )}
        </div>
      )}
    </>
  )
}

function GroupRows({ group, tree }: { group: Group; tree: ReturnType<typeof useCollapsibleTree> }) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={6}>{group.label}</td>
      </tr>
      {group.rows.map((r, i) =>
        tree.isHidden(r) ? null : (
          <tr
            key={r.id ?? `${group.type}-${i}`}
            className={r.id !== undefined && r.has_children && tree.isCollapsed(r.id) ? 'collapsed' : undefined}
            data-has-children={r.id !== undefined ? (r.has_children ? '1' : '0') : undefined}
          >
            <td className="mono dim">{r.account_code}</td>
            <td
              className={`acct-name${r.depth !== undefined ? ` depth-${Math.min(r.depth, 6)}` : ''}`}
              onClick={() => r.id !== undefined && r.has_children && tree.toggle(r.id)}
            >
              {r.id !== undefined && <span className="tree-toggle" />}
              {r.account_name} {r.path && <span className="dim small">{r.path}</span>}
            </td>
            <td className="num money money-first">{formatMoneyOrDash(r.baseline_net)}</td>
            <td className={`num money ${Number(r.variance) < 0 ? 'neg' : ''}`}>{formatMoneyOrDash(r.variance)}</td>
            <td className="num">{pctText(r.pct_variance)}</td>
            <td className="num money">{formatMoneyOrDash(r.compare_net)}</td>
          </tr>
        ),
      )}
      <tr className="subtotal">
        <td></td>
        <td>{group.label} subtotal</td>
        <td className="num money money-first">{formatMoneyOrDash(group.sub_baseline)}</td>
        <td className={`num money ${Number(group.sub_variance) < 0 ? 'neg' : ''}`}>
          {formatMoneyOrDash(group.sub_variance)}
        </td>
        <td className="num">{pctText(group.sub_pct_variance)}</td>
        <td className="num money">{formatMoneyOrDash(group.sub_compare)}</td>
      </tr>
    </>
  )
}
