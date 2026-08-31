import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PieLabelRenderProps } from 'recharts'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import type { components } from '../api/schema'
import { useAccountLevels } from '../api/useAccountLevels'
import { useAccounts } from '../api/useAccounts'
import { usePayees } from '../api/usePayees'
import { useScenarios } from '../api/useScenarios'
import { useTags } from '../api/useTags'
import { formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import PeriodPresetPicker from '../widgets/PeriodPresetPicker'

// `metric`/`dimension`/`account_type` are compile-time union types off the
// generated schema (`openapi-typescript`, driven by the backend's own
// `Enum`s — see `modules/custom_reports/enums.py`) rather than hand-typed
// string literals here, per CUSTOM_REPORTS.md's Architecture section: an
// enum member added backend-side with no matching entry in the *_LABELS
// maps below is a `tsc` error, not a silently-blank dropdown row.
type Metric = components['schemas']['Metric']
type Dimension = components['schemas']['Dimension']
type AccountTypeFilter = components['schemas']['AccountTypeFilter']
type ChartType = 'bar' | 'line' | 'area' | 'pie' | 'table'

const METRIC_LABELS: Record<Metric, string> = {
  net_amount: 'Net amount',
  debit_total: 'Debit total',
  credit_total: 'Credit total',
  entry_count: 'Entry count',
}

const DIMENSION_LABELS: Record<Dimension, string> = {
  account: 'Account',
  account_level: 'Account level',
  tag: 'Tag',
  scenario: 'Scenario',
  month: 'Month',
  quarter: 'Quarter',
  year: 'Year',
}

const ACCOUNT_TYPE_LABELS: Record<AccountTypeFilter, string> = {
  asset: 'Asset',
  liability: 'Liability',
  equity: 'Equity',
  income: 'Income',
  expense: 'Expense',
}

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: 'Bar chart',
  line: 'Line chart',
  area: 'Area chart',
  pie: 'Pie chart',
  table: 'Table',
}

function optionsOf<K extends string>(labels: Record<K, string>): { value: K; label: string }[] {
  return (Object.keys(labels) as K[]).map((value) => ({ value, label: labels[value] }))
}

const METRIC_OPTIONS = optionsOf(METRIC_LABELS)
const DIMENSION_OPTIONS = optionsOf(DIMENSION_LABELS)
const ACCOUNT_TYPE_OPTIONS = [{ value: '', label: 'Any' }, ...optionsOf(ACCOUNT_TYPE_LABELS)]
const CHART_TYPE_OPTIONS = optionsOf(CHART_TYPE_LABELS)

interface Row {
  key: string | number
  label: string
  value: string | number
}

interface CustomReportResult {
  rows: Row[]
  total: string | number
  row_count: number
  metric: Metric
  dimension: Dimension
  scenario: string
  date_from: string
  date_to: string
  account_id: number | null
  subtree: number
  tag_id: number | null
  payee_id: number | null
  account_type: string
  level_id: number | null
  today: string
  prev_from?: string
  prev_to?: string
  next_from?: string
  next_to?: string
}

// `entry_count` rows are plain integers on the wire (`repository.py`'s
// `run_report`/`run_total` never route that metric through a `NUMERIC`
// cast); every other metric is a Decimal string, same
// stringified-to-avoid-float-precision-loss convention `format/money.ts`
// already documents. `formatMoneyOrDash` would add a currency
// symbol/thousands format tuned for money, not a plain count, so counts
// get their own formatter rather than money's.
function formatValue(value: string | number, metric: Metric): string {
  if (metric === 'entry_count') return Number(value).toLocaleString()
  return formatMoneyOrDash(value)
}

function numberOf(value: string | number): number {
  return typeof value === 'number' ? value : parseFloat(value)
}

// One accent hue for the single series every bar/line/area chart here
// ever draws (one metric x one dimension is exactly one `GROUP BY`, per
// CUSTOM_REPORTS.md — never more than one series), with negative values
// picked out in the app's existing `--red` — the same diverging-by-sign
// convention `format/money.ts`'s own `.neg` class already applies to
// every negative number in the app, just carried into the chart. Pie
// mode is the one real categorical case (each slice IS a distinct
// category, simultaneously visible) — a short, hand-picked rotation of
// the app's own themed tokens, since every current theme (`index.css`)
// only defines this many distinctly-hued roles; a 9th slice would be a
// generated, non-vetted hue, so rows beyond the rotation fold into a
// trailing "Other" slice instead (`pieData` below) rather than stretching
// the rotation further.
const ACCENT = 'var(--accent)'
const NEGATIVE = 'var(--red)'
const PIE_COLORS = ['var(--accent)', 'var(--focus)', 'var(--ok)', 'var(--warn)', 'var(--red)', 'var(--ink-soft)']
const PIE_MAX_SLICES = PIE_COLORS.length

function barColor(value: string | number): string {
  return numberOf(value) < 0 ? NEGATIVE : ACCENT
}

// Folds anything past `PIE_COLORS`' own length into a trailing "Other"
// slice (summed by magnitude) rather than seating a 7th/8th hue no
// current theme actually distinguishes — see this file's top comment.
// Recharts' `Pie` sums its `dataKey` with a plain `acc + cur` reducer to
// get each slice's share of the whole circle — fine for the Cartesian
// charts below (their d3 scales coerce a numeric *string* on read), but
// `+` on two strings concatenates rather than adds, so `Pie` needs real
// numbers up front or every slice silently renders as a zero-size sector.
// `value`'s wire type is a Decimal string for every metric except
// `entry_count` (`format/money.ts`'s own documented convention). Slices
// are magnitude, not signed amount — part-to-whole has no meaningful
// negative wedge — so this takes `Math.abs` uniformly, same as the
// "Other" bucket already had to for its own sum.
function pieData(rows: Row[]): Row[] {
  const numeric = rows.map((r) => ({ ...r, value: Math.abs(numberOf(r.value)) }))
  if (numeric.length <= PIE_MAX_SLICES) return numeric
  const head = numeric.slice(0, PIE_MAX_SLICES - 1)
  const tailTotal = numeric.slice(PIE_MAX_SLICES - 1).reduce((sum, r) => sum + Math.abs(r.value), 0)
  return [...head, { key: '__other__', label: 'Other', value: tailTotal }]
}

export default function CustomReportPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const accounts = useAccounts()
  const tags = useTags()
  const payees = usePayees()
  const levels = useAccountLevels()
  const [result, setResult] = useState<CustomReportResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const metric = (searchParams.get('metric') as Metric) || 'net_amount'
  const dimension = (searchParams.get('dimension') as Dimension) || 'month'
  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const dateFrom = searchParams.get('date_from') || ''
  const dateTo = searchParams.get('date_to') || ''
  const accountId = searchParams.get('account_id') || ''
  const subtree = searchParams.get('subtree') === '1'
  const tagId = searchParams.get('tag_id') || ''
  const payeeId = searchParams.get('payee_id') || ''
  const accountType = (searchParams.get('account_type') as AccountTypeFilter) || ''
  const levelId = searchParams.get('level_id') || ''
  const chart = (searchParams.get('chart') as ChartType) || 'bar'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/custom', {
        params: {
          query: {
            metric,
            dimension,
            scenario,
            date_from: dateFrom,
            date_to: dateTo,
            account_id: accountId ? Number(accountId) : undefined,
            subtree: subtree ? 1 : 0,
            tag_id: tagId ? Number(tagId) : undefined,
            payee_id: payeeId ? Number(payeeId) : undefined,
            account_type: accountType || undefined,
            level_id: levelId ? Number(levelId) : undefined,
          },
        },
      })
      .then(({ data, error: err }) => {
        if (cancelled) return
        if (data) {
          setResult(data as unknown as CustomReportResult)
          setError(null)
        } else {
          // `service.py`'s validation errors (an unknown filter id, a
          // malformed date, `account_level` with no `level_id`) surface
          // as a plain 400 with `{detail: "..."}` — not in the generated
          // schema's declared error type (only 422 is), so read it as a
          // loosely-typed body rather than `HTTPValidationError`.
          setResult(null)
          setError((err as { detail?: string } | undefined)?.detail ?? 'Could not load this report.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [metric, dimension, scenario, dateFrom, dateTo, accountId, subtree, tagId, payeeId, accountType, levelId])

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

  const accountOptions = useMemo(
    () => [
      { value: '', label: 'Any' },
      ...(accounts ?? []).filter((a) => a.is_active).map((a) => ({ value: String(a.id), label: `${a.code} · ${a.path}` })),
    ],
    [accounts],
  )
  const tagOptions = useMemo(
    () => [{ value: '', label: 'Any' }, ...(tags ?? []).filter((t) => t.is_active).map((t) => ({ value: String(t.id), label: t.name }))],
    [tags],
  )
  const payeeOptions = useMemo(
    () => [{ value: '', label: 'Any' }, ...(payees ?? []).filter((p) => p.is_active).map((p) => ({ value: String(p.id), label: p.name }))],
    [payees],
  )
  const levelOptions = useMemo(
    () => (levels ?? []).map((l) => ({ value: String(l.id), label: `${l.name} (depth ${l.depth})` })),
    [levels],
  )

  const exportQuery =
    `metric=${metric}&dimension=${dimension}&scenario=${encodeURIComponent(scenario)}` +
    `&date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}` +
    `&account_id=${accountId}&subtree=${subtree ? 1 : 0}&tag_id=${tagId}&payee_id=${payeeId}` +
    `&account_type=${accountType}&level_id=${levelId}`

  const rows = result?.rows ?? []
  const hasNav = result?.prev_from !== undefined

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          {METRIC_LABELS[metric]} by {DIMENSION_LABELS[dimension].toLowerCase()}
          {dimension !== 'scenario' && (
            <>
              {' '}
              · Scenario <span className="mono">{scenario}</span>
            </>
          )}
        </p>
        <Link to="/app/help#custom-reports" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      <div className="bar">
        <label className="field">
          Metric
          <Combobox options={METRIC_OPTIONS} value={metric} onChange={(v) => setParams({ metric: v })} />
        </label>
        <label className="field">
          Break down by
          <Combobox
            options={DIMENSION_OPTIONS}
            value={dimension}
            onChange={(v) => {
              // `account_level` 400s server-side with no `level_id` at
              // all (`service.py`'s own "needs a level_id" check) — auto-
              // picking the first real level the moment this dimension is
              // chosen means the switch always lands on a working report,
              // same as every other dimension already does with its own
              // defaults, rather than a dead 400 until the user also
              // happens to touch the Level field that only just appeared.
              if (v === 'account_level' && !levelId && levelOptions.length > 0) {
                setParams({ dimension: v, level_id: levelOptions[0].value })
              } else {
                setParams({ dimension: v })
              }
            }}
          />
        </label>
        <label className="field">
          Chart
          <Combobox options={CHART_TYPE_OPTIONS} value={chart} onChange={(v) => setParams({ chart: v })} />
        </label>
      </div>

      <div className="bar">
        <label className="field" title={dimension === 'scenario' ? 'Ignored — comparing scenarios is the point of this breakdown' : undefined}>
          Scenario
          <Combobox
            options={(scenarios ?? []).map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
            value={scenario}
            onChange={(v) => setParams({ scenario: v })}
            disabled={dimension === 'scenario'}
          />
        </label>
        <label className="field">
          Account type
          <Combobox options={ACCOUNT_TYPE_OPTIONS} value={accountType} onChange={(v) => setParams({ account_type: v })} />
        </label>
        <label className="field">
          Account
          <Combobox options={accountOptions} value={accountId} onChange={(v) => setParams({ account_id: v })} />
        </label>
        <label className="checkline" title="Include every descendant of the selected account, not just entries posted directly to it">
          <input
            type="checkbox"
            checked={subtree}
            disabled={!accountId}
            onChange={(e) => setParams({ subtree: e.target.checked ? '1' : '' })}
          />
          + subtree
        </label>
        <label className="field">
          Tag
          <Combobox options={tagOptions} value={tagId} onChange={(v) => setParams({ tag_id: v })} />
        </label>
        <label className="field">
          Payee
          <Combobox options={payeeOptions} value={payeeId} onChange={(v) => setParams({ payee_id: v })} />
        </label>
        {dimension === 'account_level' && (
          <label className="field">
            Level
            <Combobox options={levelOptions} value={levelId} onChange={(v) => setParams({ level_id: v })} />
          </label>
        )}
      </div>

      <div className="bar">
        <label className="field">
          Period
          <PeriodPresetPicker dateFrom={dateFrom} dateTo={dateTo} onChange={(from, to) => setParams({ date_from: from, date_to: to })} />
        </label>
        <label className="field">
          From
          <DatePicker value={dateFrom} onChange={(v) => setParams({ date_from: v })} />
        </label>
        <label className="field">
          To
          <DatePicker value={dateTo} onChange={(v) => setParams({ date_to: v })} />
        </label>
        {(dateFrom || dateTo) && (
          <button type="button" className="quiet-link" onClick={() => setParams({ date_from: '', date_to: '' })}>
            Clear (unbounded)
          </button>
        )}
      </div>

      {hasNav && result && (
        <p className="bar" style={{ alignItems: 'center' }}>
          <Link className="quiet-link" to={`?${pageParams({ date_from: result.prev_from!, date_to: result.prev_to! })}`}>
            &larr; {result.prev_from!.slice(0, 7)}
          </Link>
          <Link className="quiet-link" to={`?${pageParams({ date_from: result.next_from!, date_to: result.next_to! })}`}>
            {result.next_from!.slice(0, 7)} &rarr;
          </Link>
        </p>
      )}

      {error ? (
        <p className="dim">{error}</p>
      ) : result === null ? (
        <p>Loading…</p>
      ) : (
        // `.report-frame`'s `width: fit-content` (index.css) is sized for
        // a table — it shrink-wraps to the table's own intrinsic width so
        // Export CSV/XLSX right-align above it. A chart has no intrinsic
        // width of its own (`ResponsiveContainer` fills whatever it's
        // given), so fit-content around one collapses to near-zero — only
        // table mode gets the wrapper; chart mode's export bar rides
        // `main`'s own full width instead, same as every filter `.bar`
        // above it already does.
        <div className={chart === 'table' ? 'report-frame' : undefined}>
          <p className="bar report-export">
            <a className="quiet-link" href={`/reports/custom.csv?${exportQuery}`}>
              Export CSV
            </a>
            <a className="quiet-link" href={`/reports/custom.xlsx?${exportQuery}`}>
              Export XLSX
            </a>
          </p>

          {rows.length === 0 ? (
            <p className="dim">No activity matches this configuration.</p>
          ) : chart === 'table' ? (
            <CustomReportTable result={result} rows={rows} />
          ) : (
            <CustomReportChart chart={chart} rows={rows} metric={metric} dimension={dimension} />
          )}

          <p className="dim small">
            {result.row_count} row{result.row_count !== 1 ? 's' : ''} · Total {formatValue(result.total, metric)}
          </p>
        </div>
      )}
    </>
  )
}

function CustomReportTable({ result, rows }: { result: CustomReportResult; rows: Row[] }) {
  // Plain `.ledger`, not `.ledger.report-table` — that modifier's own
  // sticky-first-column rule (index.css) hard-pins the first column to a
  // 4.5rem "account code" width, sized for every other report's Code +
  // Account shape. This table only ever has two columns (a dimension
  // label, then the metric), so it keeps `.ledger`'s money/grand-row
  // styling without inheriting a column-width assumption that doesn't fit.
  return (
    <table className="ledger">
      <thead>
        <tr>
          <th>{DIMENSION_LABELS[result.dimension]}</th>
          <th className="num money money-first">{METRIC_LABELS[result.metric]}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td>{r.label}</td>
            <td className={`num money money-first ${numberOf(r.value) < 0 ? 'neg' : ''}`}>{formatValue(r.value, result.metric)}</td>
          </tr>
        ))}
        <tr className="grand">
          <td>Total</td>
          <td className={`num money money-first ${numberOf(result.total) < 0 ? 'neg' : ''}`}>{formatValue(result.total, result.metric)}</td>
        </tr>
      </tbody>
    </table>
  )
}

// A tooltip/axis-tick formatter that reads the report's own units
// (`formatValue` — money vs. a plain count) rather than Recharts' own
// raw-number default. Typed against `unknown` rather than Recharts' own
// `ValueType` (`number | string | ReadonlyArray<number | string>`): this
// chart's single numeric `dataKey` never actually produces the
// array/undefined cases, but the callback has to admit them to satisfy
// both `<Tooltip formatter>` and `<YAxis tickFormatter>`'s signatures.
function valueTooltip(metric: Metric): (value: unknown) => string {
  return (value) => {
    if (typeof value !== 'number' && typeof value !== 'string') return ''
    return formatValue(value, metric)
  }
}

function CustomReportChart({
  chart,
  rows,
  metric,
  dimension,
}: {
  chart: ChartType
  rows: Row[]
  metric: Metric
  dimension: Dimension
}) {
  // Every mark below sets `isAnimationActive={false}`: Recharts drives its
  // entrance animation off `requestAnimationFrame`, which a backgrounded/
  // hidden browser tab throttles indefinitely — confirmed directly while
  // building this page (a headless verification pass left every series
  // stuck at its zero-value starting frame, rendering nothing, until this
  // was set). A config-driven report a user reaches for repeatedly should
  // render its data immediately regardless, not depend on the tab having
  // been in the foreground since mount.
  const formatter = valueTooltip(metric)

  if (chart === 'pie') {
    const data = pieData(rows)
    return (
      <ResponsiveContainer width="100%" height={420}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            cx="50%"
            cy="50%"
            outerRadius={150}
            isAnimationActive={false}
            label={(props: PieLabelRenderProps) => (props.payload as Row | undefined)?.label ?? ''}
          >
            {data.map((d, i) => (
              <Cell key={d.key} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
          <Legend />
          <Tooltip formatter={formatter} />
        </PieChart>
      </ResponsiveContainer>
    )
  }

  const xLabel = DIMENSION_LABELS[dimension]
  const yLabel = METRIC_LABELS[metric]

  if (chart === 'line') {
    return (
      <ResponsiveContainer width="100%" height={420}>
        <LineChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="var(--rule)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: 'var(--ink-soft)' }} />
          <YAxis stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} tickFormatter={(v) => formatter(v)} width={90} />
          <Tooltip formatter={formatter} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--rule)', color: 'var(--ink)' }} />
          <Line
            type="monotone"
            dataKey="value"
            name={yLabel}
            stroke={ACCENT}
            strokeWidth={2}
            dot={{ r: 4, fill: ACCENT }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    )
  }

  if (chart === 'area') {
    return (
      <ResponsiveContainer width="100%" height={420}>
        <AreaChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="var(--rule)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: 'var(--ink-soft)' }} />
          <YAxis stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} tickFormatter={(v) => formatter(v)} width={90} />
          <Tooltip formatter={formatter} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--rule)', color: 'var(--ink)' }} />
          <Area
            type="monotone"
            dataKey="value"
            name={yLabel}
            stroke={ACCENT}
            fill={ACCENT}
            fillOpacity={0.25}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={420}>
      <BarChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid stroke="var(--rule)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} label={{ value: xLabel, position: 'insideBottom', offset: -4, fill: 'var(--ink-soft)' }} />
        <YAxis stroke="var(--ink-soft)" tick={{ fill: 'var(--ink-soft)', fontSize: 12 }} tickFormatter={(v) => formatter(v)} width={90} />
        <Tooltip formatter={formatter} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--rule)', color: 'var(--ink)' }} />
        <Bar dataKey="value" name={yLabel} radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {rows.map((r) => (
            <Cell key={r.key} fill={barColor(r.value)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
