import type { ReactNode } from 'react'
import { Fragment, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import PeriodPresetPicker from '../widgets/PeriodPresetPicker'
import { useCollapsibleTree, type CollapsibleRow } from '../widgets/useCollapsibleTree'

// Ported from app/templates/income_statement.html (Phase 4.1) — the
// hardest data shape of the five remaining reports: rows mode (a single
// range, structurally close to every other report) and Split mode (a
// column-group-per-period matrix), discriminated by whether the response
// carries `periods_totals` (confirmed from reading `modules/reports/
// service.py::income_statement_rows`/`income_statement_matrix` directly,
// not assumed).
//
// The key simplification this component leans on, spelled out in
// income_statement.html's own comment on its split branch: a row/group's
// `periods` array (matrix mode only) is "the very same shape a single-
// period row/group has" — r.periods[i].base_net is r.base_net's split-
// view counterpart, not a different field. So rather than two parallel
// body-rendering branches, this file treats rows mode as a matrix of
// exactly one synthetic period (`periodsOf`/`periodsTotalsOf`/
// `rowPeriod`/`groupPeriod` below paper over the distinction), and only
// branches for real between the two header shapes (a single plain header
// row vs. Split's two-row period-group header) — mirroring how close the
// two branches already are in the Jinja source.
interface RowPeriod {
  base_net: string | number
  compare_net: string | number
  variance: string | number
  pct_variance: string | null
}

interface Row extends CollapsibleRow, RowPeriod {
  account_code: string
  account_name: string
  path: string
  depth: number
  // Present only in matrix-mode rows — one entry per `periodsTotals`
  // (real periods, then Totals, then Average).
  periods?: RowPeriod[]
}

interface GroupPeriod {
  base_subtotal: string | number
  compare_subtotal: string | number
  variance: string | number
  pct_variance: string | null
  // Expense groups only.
  base_pct_of_income?: string | null
  compare_pct_of_income?: string | null
  base_running_after?: string | number
  compare_running_after?: string | number
  running_variance?: string | number
  running_pct_variance?: string | null
  base_running_pct_of_income?: string | null
  compare_running_pct_of_income?: string | null
}

interface Group extends GroupPeriod {
  name: string
  rows: Row[]
  periods?: GroupPeriod[]
}

// A whole single-period `income_statement_rows()` result — what each
// entry of matrix mode's own `periods_totals` is, and what the rows-mode
// top-level response already structurally is (confirmed directly from
// `service.income_statement_matrix`'s own comment: "kept as-is rather
// than reshaped, so a caller reads periods_totals[i].x the same way the
// unsplit result reads x directly").
interface PeriodTotals {
  income_groups: Group[]
  expense_groups: Group[]
  total_base_income: string | number
  total_compare_income: string | number
  income_variance_amount: string | number
  income_variance: string | null
  net_income: string | number
  compare_net_income: string | number
  net_income_variance_amount: string | number
  net_income_variance: string | null
  net_income_pct_of_income: string | null
  compare_net_income_pct_of_income: string | null
  has_compare: boolean
}

interface PeriodDescriptor {
  label: string
  date_from: string
  date_to: string
  partial: boolean
  is_total?: boolean
  is_average?: boolean
}

interface CommonFields {
  scenario: string
  compare: string
  date_from: string
  date_to: string
  zeros: number
  pct_of_base: number
  split: string
  today: string
  prev_from: string
  prev_to: string
  next_from: string
  next_to: string
}

type RowsResult = PeriodTotals & CommonFields & { periods: [] }
type MatrixResult = CommonFields & {
  income_groups: Group[]
  expense_groups: Group[]
  periods_totals: PeriodTotals[]
  has_compare: boolean
  periods: PeriodDescriptor[]
}
type IncomeStatementResult = RowsResult | MatrixResult

function isMatrixResult(r: IncomeStatementResult): r is MatrixResult {
  return 'periods_totals' in r
}

// The three functions the "rows mode is a one-period matrix" reading
// depends on — see this file's own top comment.
function periodsOf(r: IncomeStatementResult): PeriodDescriptor[] {
  return isMatrixResult(r) ? r.periods : [{ label: '', date_from: r.date_from, date_to: r.date_to, partial: false }]
}
function periodsTotalsOf(r: IncomeStatementResult): PeriodTotals[] {
  return isMatrixResult(r) ? r.periods_totals : [r]
}
function rowPeriod(row: Row, i: number, matrix: boolean): RowPeriod {
  return matrix ? row.periods![i] : row
}
function groupPeriod(group: Group, i: number, matrix: boolean): GroupPeriod {
  return matrix ? group.periods![i] : group
}

function colCls(i: number, multiPeriod: boolean): string {
  return i === 0 ? ' money-first' : multiPeriod ? ' period-start' : ''
}
function aggCls(p: PeriodDescriptor): string {
  return p.is_average ? ' period-agg-average' : p.is_total ? ' period-agg' : ''
}

// `var()` in income_statement.html — a bare Decimal string printed as-is
// (never through formatMoney's own thousands/symbol formatting, which is
// for currency, not a percentage), red only when negative.
function pctText(pct: string | number | null | undefined): ReactNode {
  if (pct === null || pct === undefined) return <span className="dim">—</span>
  return <span className={Number(pct) < 0 ? 'neg' : undefined}>{pct}%</span>
}

// `amt()` in income_statement.html — a money figure plus an optional
// "(NN.N% of income)" annotation, dim/small, never colored.
function amtText(value: string | number, pct: string | number | null | undefined): ReactNode {
  return (
    <>
      {formatMoneyOrDash(value)}
      {pct !== null && pct !== undefined && <span className="dim small"> ({pct}%)</span>}
    </>
  )
}

const COLLAPSE_KEY = 'postwarden-income-statement-collapsed'

export default function IncomeStatementPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<IncomeStatementResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const compare = searchParams.get('compare') || ''
  const today = new Date().toISOString().slice(0, 10)
  const dateFrom = searchParams.get('date_from') || `${today.slice(0, 7)}-01`
  const dateTo = searchParams.get('date_to') || today
  const split = searchParams.get('split') || ''
  const zeros = searchParams.get('zeros') === '1'
  const pctOfBase = searchParams.get('pct_of_base') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/income-statement', {
        params: {
          query: {
            scenario,
            compare,
            date_from: dateFrom,
            date_to: dateTo,
            zeros: zeros ? 1 : 0,
            pct_of_base: pctOfBase ? 1 : 0,
            split,
          },
        },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as IncomeStatementResult)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, compare, dateFrom, dateTo, split, zeros, pctOfBase])

  const matrix = result !== null && isMatrixResult(result)
  const periods = result ? periodsOf(result) : []
  const periodsTotals = result ? periodsTotalsOf(result) : []
  const hasCompare = result?.has_compare ?? false

  const allRows = result ? [...result.income_groups, ...result.expense_groups].flatMap((g) => g.rows) : []
  const tree = useCollapsibleTree(COLLAPSE_KEY, allRows)

  function setParams(overrides: Record<string, string>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(overrides)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
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
    `scenario=${encodeURIComponent(scenario)}&compare=${encodeURIComponent(compare)}` +
    `&date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}` +
    `&zeros=${zeros ? 1 : 0}&pct_of_base=${pctOfBase ? 1 : 0}&split=${encodeURIComponent(split)}`

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          Scenario <span className="mono">{scenario}</span>
          {compare && (
            <>
              {' '}
              vs. <span className="mono">{compare}</span>
            </>
          )}
          {matrix && result && isMatrixResult(result) && (
            <>
              {' '}
              · split {split} ({result.periods.length - 2} period{result.periods.length - 2 !== 1 ? 's' : ''} + Total
              + Average)
            </>
          )}
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
            onChange={(v) => setParams({ scenario: v })}
          />
        </label>
        <label className="field">
          Compare to
          <Combobox
            options={[{ value: '', label: 'None' }, ...(scenarios ?? []).map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))]}
            value={compare}
            onChange={(v) => setParams({ compare: v })}
          />
        </label>
        <label className="field">
          Split
          <Combobox
            options={[
              { value: '', label: 'No split' },
              { value: 'monthly', label: 'Monthly' },
              { value: 'quarterly', label: 'Quarterly' },
              { value: 'yearly', label: 'Yearly' },
            ]}
            value={split}
            onChange={(v) => setParams({ split: v })}
          />
        </label>
        <label className="field">
          Period
          <PeriodPresetPicker
            dateFrom={dateFrom}
            dateTo={dateTo}
            onChange={(from, to) => setParams({ date_from: from, date_to: to })}
          />
        </label>
        <label className="field">
          From
          <DatePicker value={dateFrom} onChange={(v) => setParams({ date_from: v })} />
        </label>
        <label className="field">
          To
          <DatePicker value={dateTo} onChange={(v) => setParams({ date_to: v })} />
        </label>
      </div>

      {result && (
        <p className="bar" style={{ alignItems: 'center' }}>
          <Link
            className="quiet-link"
            to={`?${pageParams({ date_from: result.prev_from, date_to: result.prev_to })}`}
          >
            &larr; {result.prev_from.slice(0, 7)}
          </Link>
          <Link
            className="quiet-link"
            to={`?${pageParams({ date_from: result.next_from, date_to: result.next_to })}`}
          >
            {result.next_from.slice(0, 7)} &rarr;
          </Link>
        </p>
      )}

      <p className="bar" style={{ alignItems: 'center' }}>
        <label className="checkline">
          <input type="checkbox" checked={zeros} onChange={(e) => setParams({ zeros: e.target.checked ? '1' : '' })} />
          show zero balances
        </label>
        {compare && (
          <label
            className="checkline"
            title="Default: Scenario − Compare, as a % of Compare. Checked: Compare − Scenario, as a % of Scenario."
          >
            <input
              type="checkbox"
              checked={pctOfBase}
              onChange={(e) => setParams({ pct_of_base: e.target.checked ? '1' : '' })}
            />
            Flip variance direction
          </label>
        )}
      </p>

      {result === null ? (
        <p>Loading…</p>
      ) : (
        <div className="report-frame">
          <p className="bar report-export">
            <a className="quiet-link" href={`/reports/income-statement.csv?${exportQuery}`}>
              Export CSV
            </a>
            <a className="quiet-link" href={`/reports/income-statement.xlsx?${exportQuery}`}>
              Export XLSX
            </a>
          </p>

          {matrix ? (
            <div className="table-scroll">
              <IncomeStatementTable
                result={result}
                periods={periods}
                periodsTotals={periodsTotals}
                matrix={matrix}
                hasCompare={hasCompare}
                tree={tree}
                scroll
              />
            </div>
          ) : (
            <IncomeStatementTable
              result={result}
              periods={periods}
              periodsTotals={periodsTotals}
              matrix={matrix}
              hasCompare={hasCompare}
              tree={tree}
              scroll={false}
            />
          )}

          {periods.some((p) => p.partial) && (
            <p className="dim small">
              * covers only part of that calendar period — clipped to the selected From/To range, not a full
              month/quarter/year.
            </p>
          )}
          {result.income_groups.length === 0 && result.expense_groups.length === 0 && (
            <p className="dim">No income or expense activity in this period.</p>
          )}
        </div>
      )}
    </>
  )
}

function IncomeStatementTable({
  result,
  periods,
  periodsTotals,
  matrix,
  hasCompare,
  tree,
  scroll,
}: {
  result: IncomeStatementResult
  periods: PeriodDescriptor[]
  periodsTotals: PeriodTotals[]
  matrix: boolean
  hasCompare: boolean
  tree: ReturnType<typeof useCollapsibleTree>
  scroll: boolean
}) {
  const multiPeriod = periods.length > 1
  const colspan = matrix ? 2 + periods.length * (hasCompare ? 4 : 1) : hasCompare ? 6 : 3

  return (
    <table className="ledger report-table">
      <thead>
        {scroll ? (
          <>
            <tr>
              <th rowSpan={2}>Code</th>
              <th rowSpan={2}>Account</th>
              {periods.map((p, i) => (
                <th
                  key={i}
                  className={`num period-label${colCls(i, multiPeriod)}${aggCls(p)}`}
                  colSpan={hasCompare ? 4 : 1}
                  title={`${p.date_from} – ${p.date_to}`}
                >
                  {p.label}
                  {p.partial && <sup>*</sup>}
                </th>
              ))}
            </tr>
            <tr>
              {periods.map((p, i) => (
                <Fragment key={i}>
                  <th className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>{result.scenario}</th>
                  {hasCompare && (
                    <>
                      <th className={`num money${aggCls(p)}`}>Variance</th>
                      <th className={`num${aggCls(p)}`}>% variance</th>
                      <th className={`num money${aggCls(p)}`}>{result.compare}</th>
                    </>
                  )}
                </Fragment>
              ))}
            </tr>
          </>
        ) : (
          <tr>
            <th>Code</th>
            <th>Account</th>
            <th className="num money money-first">{result.scenario}</th>
            {hasCompare && (
              <>
                <th className="num money">Variance</th>
                <th className="num">% variance</th>
                <th className="num money">{result.compare}</th>
              </>
            )}
          </tr>
        )}
      </thead>
      <tbody>
        {result.income_groups.map((g) => (
          <GroupBlock
            key={g.name}
            group={g}
            periods={periods}
            matrix={matrix}
            hasCompare={hasCompare}
            multiPeriod={multiPeriod}
            tree={tree}
            showSubtotal={result.income_groups.length > 1}
            colspan={colspan}
          />
        ))}
        <tr className="subtotal">
          <td></td>
          <td>Total income</td>
          {periods.map((p, i) => {
            const pt = periodsTotals[i]
            return (
              <Fragment key={i}>
                <td className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>{formatMoneyOrDash(pt.total_base_income)}</td>
                {hasCompare && (
                  <>
                    <td className={`num money${aggCls(p)} ${Number(pt.income_variance_amount) < 0 ? 'neg' : ''}`}>
                      {formatMoneyOrDash(pt.income_variance_amount)}
                    </td>
                    <td className={`num${aggCls(p)}`}>{pctText(pt.income_variance)}</td>
                    <td className={`num money${aggCls(p)}`}>{formatMoneyOrDash(pt.total_compare_income)}</td>
                  </>
                )}
              </Fragment>
            )
          })}
        </tr>

        {result.expense_groups.length > 0 ? (
          result.expense_groups.map((g, gi) => (
            <ExpenseGroupBlock
              key={g.name}
              group={g}
              periods={periods}
              matrix={matrix}
              hasCompare={hasCompare}
              multiPeriod={multiPeriod}
              tree={tree}
              isLast={gi === result.expense_groups.length - 1}
              colspan={colspan}
            />
          ))
        ) : (
          <tr className="grand">
            <td></td>
            <td>Net income</td>
            {periods.map((p, i) => {
              const pt = periodsTotals[i]
              return (
                <Fragment key={i}>
                  <td
                    className={`num money${colCls(i, multiPeriod)}${aggCls(p)} ${Number(pt.net_income) < 0 ? 'neg' : ''}`}
                  >
                    {amtText(pt.net_income, pt.net_income_pct_of_income)}
                  </td>
                  {hasCompare && (
                    <>
                      <td className={`num money${aggCls(p)} ${Number(pt.net_income_variance_amount) < 0 ? 'neg' : ''}`}>
                        {formatMoneyOrDash(pt.net_income_variance_amount)}
                      </td>
                      <td className={`num${aggCls(p)}`}>{pctText(pt.net_income_variance)}</td>
                      <td className={`num money${aggCls(p)} ${Number(pt.compare_net_income) < 0 ? 'neg' : ''}`}>
                        {amtText(pt.compare_net_income, pt.compare_net_income_pct_of_income)}
                      </td>
                    </>
                  )}
                </Fragment>
              )
            })}
          </tr>
        )}
      </tbody>
    </table>
  )
}

function GroupBlock({
  group,
  periods,
  matrix,
  hasCompare,
  multiPeriod,
  tree,
  showSubtotal,
  colspan,
}: {
  group: Group
  periods: PeriodDescriptor[]
  matrix: boolean
  hasCompare: boolean
  multiPeriod: boolean
  tree: ReturnType<typeof useCollapsibleTree>
  showSubtotal: boolean
  colspan: number
}) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={colspan}>{group.name}</td>
      </tr>
      {group.rows.map((r) =>
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
            {periods.map((p, i) => {
              const rp = rowPeriod(r, i, matrix)
              return (
                <Fragment key={i}>
                  <td className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>{formatMoneyOrDash(rp.base_net)}</td>
                  {hasCompare && (
                    <>
                      <td className={`num money${aggCls(p)} ${Number(rp.variance) < 0 ? 'neg' : ''}`}>
                        {formatMoneyOrDash(rp.variance)}
                      </td>
                      <td className={`num${aggCls(p)}`}>{pctText(rp.pct_variance)}</td>
                      <td className={`num money${aggCls(p)}`}>{formatMoneyOrDash(rp.compare_net)}</td>
                    </>
                  )}
                </Fragment>
              )
            })}
          </tr>
        ),
      )}
      {showSubtotal && (
        <tr className="subtotal">
          <td></td>
          <td>Total {group.name}</td>
          {periods.map((p, i) => {
            const gp = groupPeriod(group, i, matrix)
            return (
              <Fragment key={i}>
                <td className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>{formatMoneyOrDash(gp.base_subtotal)}</td>
                {hasCompare && (
                  <>
                    <td className={`num money${aggCls(p)} ${Number(gp.variance) < 0 ? 'neg' : ''}`}>
                      {formatMoneyOrDash(gp.variance)}
                    </td>
                    <td className={`num${aggCls(p)}`}>{pctText(gp.pct_variance)}</td>
                    <td className={`num money${aggCls(p)}`}>{formatMoneyOrDash(gp.compare_subtotal)}</td>
                  </>
                )}
              </Fragment>
            )
          })}
        </tr>
      )}
    </>
  )
}

function ExpenseGroupBlock({
  group,
  periods,
  matrix,
  hasCompare,
  multiPeriod,
  tree,
  isLast,
  colspan,
}: {
  group: Group
  periods: PeriodDescriptor[]
  matrix: boolean
  hasCompare: boolean
  multiPeriod: boolean
  tree: ReturnType<typeof useCollapsibleTree>
  isLast: boolean
  colspan: number
}) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={colspan}>{group.name}</td>
      </tr>
      {group.rows.map((r) =>
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
            {periods.map((p, i) => {
              const rp = rowPeriod(r, i, matrix)
              return (
                <Fragment key={i}>
                  <td className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>{formatMoneyOrDash(rp.base_net)}</td>
                  {hasCompare && (
                    <>
                      <td className={`num money${aggCls(p)} ${Number(rp.variance) < 0 ? 'neg' : ''}`}>
                        {formatMoneyOrDash(rp.variance)}
                      </td>
                      <td className={`num${aggCls(p)}`}>{pctText(rp.pct_variance)}</td>
                      <td className={`num money${aggCls(p)}`}>{formatMoneyOrDash(rp.compare_net)}</td>
                    </>
                  )}
                </Fragment>
              )
            })}
          </tr>
        ),
      )}
      <tr className="subtotal">
        <td></td>
        <td>Total {group.name}</td>
        {periods.map((p, i) => {
          const gp = groupPeriod(group, i, matrix)
          return (
            <Fragment key={i}>
              <td className={`num money${colCls(i, multiPeriod)}${aggCls(p)}`}>
                {amtText(gp.base_subtotal, gp.base_pct_of_income)}
              </td>
              {hasCompare && (
                <>
                  <td className={`num money${aggCls(p)} ${Number(gp.variance) < 0 ? 'neg' : ''}`}>
                    {formatMoneyOrDash(gp.variance)}
                  </td>
                  <td className={`num${aggCls(p)}`}>{pctText(gp.pct_variance)}</td>
                  <td className={`num money${aggCls(p)}`}>{amtText(gp.compare_subtotal, gp.compare_pct_of_income)}</td>
                </>
              )}
            </Fragment>
          )
        })}
      </tr>
      <tr className="grand">
        <td></td>
        <td>{isLast ? 'Net income' : `Net income after ${group.name}`}</td>
        {periods.map((p, i) => {
          const gp = groupPeriod(group, i, matrix)
          return (
            <Fragment key={i}>
              <td
                className={`num money${colCls(i, multiPeriod)}${aggCls(p)} ${Number(gp.base_running_after) < 0 ? 'neg' : ''}`}
              >
                {amtText(gp.base_running_after!, gp.base_running_pct_of_income)}
              </td>
              {hasCompare && (
                <>
                  <td className={`num money${aggCls(p)} ${Number(gp.running_variance) < 0 ? 'neg' : ''}`}>
                    {formatMoneyOrDash(gp.running_variance!)}
                  </td>
                  <td className={`num${aggCls(p)}`}>{pctText(gp.running_pct_variance)}</td>
                  <td className={`num money${aggCls(p)} ${Number(gp.compare_running_after) < 0 ? 'neg' : ''}`}>
                    {amtText(gp.compare_running_after!, gp.compare_running_pct_of_income)}
                  </td>
                </>
              )}
            </Fragment>
          )
        })}
      </tr>
    </>
  )
}
