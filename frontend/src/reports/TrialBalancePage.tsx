import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getCoreRowModel, getExpandedRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatMoney, isZeroAmount } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import { buildRowTree, useExpandedTree, type ExpandedTreeState, type TreeNode, type TreeRow } from '../widgets/useExpandedTree'

// The Point-in-time report archetype's canonical screen: an account tree
// as of a given date. ROADMAP.md S1's proof-of-concept port to
// TanStack Table (headless) — the table's own markup/CSS
// (`table.ledger.report-table`) is unchanged from before the port; only
// the tree-building/expansion mechanics underneath it moved from
// `useCollapsibleTree` to `useExpandedTree` + a real `useReactTable`
// instance per type group. See BalanceSheetPage.tsx for the same port
// applied to a differently-shaped (flat sections, no `grouped` wrapper)
// response.
//
// GET /reports/trial-balance's own response is a plain `dict`
// (`modules/reports/router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}` — same gap `tags/TagsPage.tsx`'s own
// comment documents for GET /tags, cast through these local interfaces
// instead.
interface Row extends TreeRow {
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
  // for exactly this reason, so this is a type-accuracy fix, not a
  // behavior change.
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
// every control change here is a real (if client-side, via react-router)
// navigation to a new URL, so the page stays
// bookmarkable/shareable/back-button-able, and the prev/next "as of"
// links (below) can be real `<Link>`s instead of onClick handlers.
export default function TrialBalancePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<TrialBalanceResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const asOf = searchParams.get('as_of') || ''
  const zeros = searchParams.get('zeros') === '1'
  const raw = searchParams.get('raw') === '1'

  // Which of the two empty-state messages below applies — "nothing's
  // ever been posted to this scenario" vs. "this scenario has activity,
  // just none as of the selected date" — hinges on whether the scenario
  // itself has ever had an entry, not just whether this particular query
  // came back empty.
  const scenarioRow = (scenarios ?? []).find((s) => s.code === scenario)

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
  // useExpandedTree needs so a row's collapsed-or-not entry exists
  // regardless of which section (Assets, Liabilities, ...) a given account
  // sits in; the synthetic "Retained Earnings" node (a real parent/children
  // triple, `domain.accounts.earnings_rows`) is registered here exactly
  // like a real account is, unlike its old flat, id-less, tree-invisible
  // shape. One shared expanded-state record, fed into a separate
  // `useReactTable` per group below — safe, since no real account's
  // `parent_id` ever crosses a type boundary, and TanStack ignores a
  // record entry for an id its own table instance never sees.
  const allRows = result ? result.grouped.flatMap((g) => g.rows) : []
  const { expanded, onExpandedChange } = useExpandedTree(COLLAPSE_KEY, allRows)

  // `replace: true`, unlike the prev/next `<Link>`s below (a genuine
  // history *push*) — deliberate, not a blind default. `DatePicker.tsx`'s
  // own text field fires `onChange` per keystroke, not once on
  // blur/commit the way a native `<input type="date">` fires `change`;
  // pushing a new history entry per keystroke while typing an as-of date
  // would spam "back" with a mid-typing state nobody actually wants to
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
      <div className="page-head">
        <p className="page-sub">
          {asOf ? `As of ${asOf}` : 'Through today'} · scenario <span className="mono">{scenario}</span>
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
                <GroupRows key={g.type} group={g} expanded={expanded} onExpandedChange={onExpandedChange}
                           scenario={scenario} raw={raw}
                           asOf={result.as_of} monthStart={result.as_of.slice(0, 7) + '-01'} />
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
        <p className="dim">
          {scenarioRow && scenarioRow.entry_count === 0 ? (
            <>
              No entries posted to this scenario yet. Post your first entry from{' '}
              <Link className="quiet-link" to="/app/entries?new=1">
                + New entry
              </Link>
              .
            </>
          ) : (
            <>No activity in this scenario as of {asOf || 'today'}. Try an earlier — or blank — "as of" date.</>
          )}
        </p>
      )}
    </>
  )
}

// One `useReactTable` instance per group — TanStack needs a nested `data`
// tree (`getSubRows`), and each type group (Assets, Income, ...) is
// already its own self-contained tree, so there's no need for one
// page-wide table spanning every group the way `expanded` state does.
// `columns` is a single throwaway entry: this component still hand-renders
// every `<td>` itself below (same JSX as before the port), so nothing here
// reads through TanStack's own cell/column model — `useReactTable` just
// needs *a* non-empty `columns` array to construct the table instance.
const NO_COLUMNS: ColumnDef<TreeNode<Row>>[] = [{ id: 'row' }]

function GroupRows({ group, expanded, onExpandedChange, scenario, raw, asOf, monthStart }: {
  group: Group; expanded: ExpandedTreeState['expanded']; onExpandedChange: ExpandedTreeState['onExpandedChange']
  scenario: string; raw: boolean; asOf: string; monthStart: string
}) {
  // trial_balance.html's own `entry_link()` macro: a leaf row's non-zero
  // balance is a link straight through to the Journal, pre-filtered to
  // exactly the entries behind it. `date_from` only applies to a flow
  // (income/expense) account, and only outside `raw` mode — a balance
  // account (asset/liability/equity) always shows its full cumulative
  // total through `as_of`, so bounding it below would exclude real
  // contributing entries; a flow account's *default* view is already
  // month-to-date (the simulated close), so the drill-through matches
  // what's actually on screen rather than reaching further back than the
  // figure itself represents.
  const entryLink = (code: string, isFlow: boolean) =>
    `/app/entries?scenario=${encodeURIComponent(scenario)}` +
    `&date_from=${isFlow && !raw ? monthStart : ''}&date_to=${asOf}&account=${encodeURIComponent(code)}`
  const isFlowType = group.type === 'income' || group.type === 'expense'

  const data = useMemo(() => buildRowTree(group.rows), [group.rows])
  const table = useReactTable({
    data,
    columns: NO_COLUMNS,
    getRowId: (row, index, parent) =>
      row.id !== undefined ? String(row.id) : `${parent ? parent.id + '-' : ''}idx-${index}`,
    getSubRows: (row) => row.subRows,
    state: { expanded },
    onExpandedChange,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  })

  return (
    <>
      <tr className="type-head">
        <td colSpan={4}>{group.label}</td>
      </tr>
      {table.getRowModel().rows.map((row) => {
        const r = row.original
        return (
          <tr
            key={row.id}
            className={r.has_children && !row.getIsExpanded() ? 'collapsed' : undefined}
            data-has-children={r.has_children ? '1' : '0'}
          >
            <td className="mono dim">{r.account_code}</td>
            <td
              className={`acct-name depth-${Math.min(r.depth, 6)}`}
              onClick={r.has_children ? row.getToggleExpandedHandler() : undefined}
            >
              <span className="tree-toggle" />
              {r.account_name} {r.path && <span className="dim small">{r.path}</span>}
            </td>
            <td className="num money money-first">
              {isZeroAmount(r.debit_balance) ? '' : (
                <Link className="amount-link" to={entryLink(r.account_code, isFlowType)}>{formatMoney(r.debit_balance)}</Link>
              )}
            </td>
            <td className="num money">
              {isZeroAmount(r.credit_balance) ? '' : (
                <Link className="amount-link" to={entryLink(r.account_code, isFlowType)}>{formatMoney(r.credit_balance)}</Link>
              )}
            </td>
          </tr>
        )
      })}
      {group.show_type_total && (
        <tr className="subtotal">
          <td></td>
          <td>{group.label} subtotal</td>
          <td className="num money money-first">{isZeroAmount(group.sub_debits) ? '' : formatMoney(group.sub_debits)}</td>
          <td className="num money">{isZeroAmount(group.sub_credits) ? '' : formatMoney(group.sub_credits)}</td>
        </tr>
      )}
    </>
  )
}
