import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatDate } from '../format/date'
import { formatMoney, formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import PeriodPresetPicker from '../widgets/PeriodPresetPicker'

// Ported from app/templates/cash_flow.html (Phase 4.1) — the first
// Range/period report screen (Income Statement/Cash Flow, per
// UI_CONSISTENCY_AUDIT.md §1), so the first to use URL-state date_from/
// date_to instead of a single as_of, and the first to use the new
// PeriodPresetPicker widget. Unlike every Point-in-time report so far
// (Trial Balance, Balance Sheet), this report has no account hierarchy —
// flat sections, no useCollapsibleTree.
//
// GET /reports/cash-flow's own response is a plain `dict`
// (`modules/reports/router.py`), same cast-through-a-local-interface gap
// every report screen documents.
interface CashFlowRow {
  account_id: number
  account_code: string
  account_name: string
  parent_path: string
  amount: string | number
  flagged: boolean
  netted_from: { account_code: string; account_name: string; amount: string | number }[]
}

interface FlaggedEntry {
  id: string
  entry_date: string
  description: string
  payee: string | null
}

interface TieOut {
  ok: boolean
  statement_total: string | number
  cash_leg_net: string | number
  balance_delta: string | number
  beginning: string | number
  ending: string | number
}

interface CashFlowResult {
  inflows: CashFlowRow[]
  outflows: CashFlowRow[]
  ledger_adjustments: CashFlowRow[]
  total_inflows: string
  total_outflows: string
  total_adjustments: string
  net_change: string
  flagged_entries: FlaggedEntry[]
  tie_out: TieOut
  scenario: string
  date_from: string
  date_to: string
  today: string
  prev_from: string
  prev_to: string
  next_from: string
  next_to: string
}

export default function CashFlowPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<CashFlowResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const today = new Date().toISOString().slice(0, 10)
  const dateFrom = searchParams.get('date_from') || `${today.slice(0, 7)}-01`
  const dateTo = searchParams.get('date_to') || today

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/cash-flow', {
        params: { query: { scenario, date_from: dateFrom, date_to: dateTo } },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as CashFlowResult)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, dateFrom, dateTo])

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

  const exportQuery = `scenario=${encodeURIComponent(scenario)}&date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          {dateFrom} – {dateTo} · scenario <span className="mono">{scenario}</span>
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
          <Link className="quiet-link" to={`?${pageParams({ date_from: result.prev_from, date_to: result.prev_to })}`}>
            &larr; {result.prev_from.slice(0, 7)}
          </Link>
          <Link className="quiet-link" to={`?${pageParams({ date_from: result.next_from, date_to: result.next_to })}`}>
            {result.next_from.slice(0, 7)} &rarr;
          </Link>
        </p>
      )}

      {result === null ? (
        <p>Loading…</p>
      ) : (
        <>
          {!result.tie_out.ok && (
            <div className="flash flash-warn" style={{ marginBottom: '1.2rem' }}>
              Tie-out check failed: statement total {formatMoney(result.tie_out.statement_total)} vs. cash-account
              leg activity {formatMoney(result.tie_out.cash_leg_net)} vs. cash-account balance change{' '}
              {formatMoney(result.tie_out.balance_delta)}. These three should always match exactly — an
              untagged/mistagged account, a mis-attributed split, or a wrongly included/excluded transfer is the
              likely cause.
            </div>
          )}

          {result.flagged_entries.length > 0 && (
            <div className="flash flash-warn" style={{ marginBottom: '1.2rem' }}>
              {result.flagged_entries.length} {result.flagged_entries.length === 1 ? 'transaction' : 'transactions'}{' '}
              in this range post to more than one cash account at once — attributed correctly, but worth a manual
              glance since the split wasn't a simple one-cash-leg case:
              <ul style={{ margin: '0.4rem 0 0 1.1rem', padding: 0 }}>
                {result.flagged_entries.map((e) => (
                  <li key={e.id}>
                    {formatDate(e.entry_date)} — {e.description}
                    {e.payee && ` (${e.payee})`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="report-frame">
            <p className="bar report-export">
              <a className="quiet-link" href={`/reports/cash-flow.csv?${exportQuery}`}>
                Export CSV
              </a>
              <a className="quiet-link" href={`/reports/cash-flow.xlsx?${exportQuery}`}>
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
                <tr className="subtotal">
                  <td></td>
                  <td>Beginning cash balance</td>
                  <td className="num money money-first">{formatMoneyOrDash(result.tie_out.beginning)}</td>
                </tr>

                <CashFlowSection label="Inflows" rows={result.inflows} emptyText="No inflows in this range."
                                 scenario={result.scenario} dateFrom={result.date_from} dateTo={result.date_to} />
                <tr className="subtotal">
                  <td></td>
                  <td>Total inflows</td>
                  <td className="num money money-first">{formatMoneyOrDash(result.total_inflows)}</td>
                </tr>

                <CashFlowSection label="Outflows" rows={result.outflows} emptyText="No outflows in this range."
                                 scenario={result.scenario} dateFrom={result.date_from} dateTo={result.date_to} />
                <tr className="subtotal">
                  <td></td>
                  <td>Total outflows</td>
                  <td className="num money money-first">{formatMoneyOrDash(result.total_outflows)}</td>
                </tr>

                {result.ledger_adjustments.length > 0 && (
                  <>
                    <tr className="type-head">
                      <td colSpan={3}>
                        Ledger adjustments <span className="dim small">(not real cash flow — net-worth setup/correction)</span>
                      </td>
                    </tr>
                    {result.ledger_adjustments.map((r) => (
                      <CashFlowRowTr key={r.account_id} row={r} scenario={result.scenario}
                                     dateFrom={result.date_from} dateTo={result.date_to} />
                    ))}
                    <tr className="subtotal">
                      <td></td>
                      <td>Total ledger adjustments</td>
                      <td className="num money money-first">{formatMoneyOrDash(result.total_adjustments)}</td>
                    </tr>
                  </>
                )}

                <tr className={`grand${result.tie_out.ok ? '' : ' out-of-balance'}`}>
                  <td></td>
                  <td>
                    Net change in cash
                    {!result.tie_out.ok && <span className="small dim"> (tie-out failed — see above)</span>}
                  </td>
                  <td className="num money money-first">{formatMoneyOrDash(result.net_change)}</td>
                </tr>
                <tr className="subtotal">
                  <td></td>
                  <td>Ending cash balance</td>
                  <td className="num money money-first">{formatMoneyOrDash(result.tie_out.ending)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}

function CashFlowSection({ label, rows, emptyText, scenario, dateFrom, dateTo }: {
  label: string; rows: CashFlowRow[]; emptyText: string
  scenario: string; dateFrom: string; dateTo: string
}) {
  return (
    <>
      <tr className="type-head">
        <td colSpan={3}>{label}</td>
      </tr>
      {rows.length === 0 ? (
        <tr>
          <td colSpan={3} className="dim">
            {emptyText}
          </td>
        </tr>
      ) : (
        rows.map((r) => <CashFlowRowTr key={r.account_id} row={r} scenario={scenario} dateFrom={dateFrom} dateTo={dateTo} />)
      )}
    </>
  )
}

function CashFlowRowTr({ row, scenario, dateFrom, dateTo }: {
  row: CashFlowRow; scenario: string; dateFrom: string; dateTo: string
}) {
  return (
    <tr>
      <td className="mono dim">{row.account_code}</td>
      <td>
        {row.account_name} {row.parent_path && <span className="dim small">{row.parent_path}</span>}
        {row.flagged && (
          <span className="dim small" title="Attributed from a transaction with more than one cash leg">
            {' '}
            ·multi-cash
          </span>
        )}
        {row.netted_from.length > 0 && (
          <>
            <br />
            <span className="dim small">
              net of{' '}
              {row.netted_from.map((n, i) => (
                <span key={n.account_code}>
                  {n.account_name} {formatMoney(n.amount)}
                  {i < row.netted_from.length - 1 && ', '}
                </span>
              ))}
            </span>
          </>
        )}
      </td>
      {/* cash_flow.html's own entry_link — same pattern as Balance
          Sheet's (drills through regardless of amount), but with the
          report's own date_from/date_to range instead of a single as_of,
          since Cash Flow has no month-to-date-vs-cumulative distinction
          to make: every row here already represents activity strictly
          within this range. */}
      <td className="num money money-first">
        <Link className="amount-link"
              to={`/app/entries?scenario=${encodeURIComponent(scenario)}&date_from=${dateFrom}&date_to=${dateTo}&account=${encodeURIComponent(row.account_code)}`}>
          {formatMoneyOrDash(row.amount)}
        </Link>
      </td>
    </tr>
  )
}
