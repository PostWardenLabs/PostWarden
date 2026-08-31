import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { formatDate } from '../format/date'
import { formatMoneyOrDash } from '../format/money'
import { useStagingPendingCount } from '../staging/useStagingPendingCount'

// The landing page: net worth, month-to-date income/expenses, recent
// activity, and upcoming scheduled entries.
//
// `GET /dashboard`'s own response is a plain `dict` (no Pydantic model,
// same as every report route), so this casts through a local interface —
// the same gap every report screen's own comment already documents.
interface FlowRow {
  id: string
  entry_date?: string
  next_date?: string
  description: string
  payee_name: string | null
  total_debits: string | number
  // `null` means "more than one account on this side" — the backend's
  // own `_flow_by_id` collapses that case rather than baking an
  // `<em>multiple</em>` marker into an HTML string; `FlowLabel` below is
  // what actually renders that italic fallback.
  debit_name: string | null
  credit_name: string | null
}

interface DashboardSummary {
  today: string
  month_label: string
  net_worth: string | number
  mtd_income: string | number
  mtd_expenses: string | number
  mtd_net: string | number
  recent: FlowRow[]
  upcoming: FlowRow[]
}

function isNeg(value: string | number): boolean {
  return Number(value) < 0
}

// "Salary Income → Cash" — which account(s) the money came from and
// which it landed in. Always rendered, never conditionally hidden: even
// a zero-line row (which shouldn't happen in practice) resolves both
// sides to "multiple" rather than an empty string.
function FlowLabel({ row }: { row: FlowRow }) {
  return (
    <span className="activity-flow dim small">
      {row.credit_name ?? <em>multiple</em>} → {row.debit_name ?? <em>multiple</em>}
    </span>
  )
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const pendingCount = useStagingPendingCount()

  useEffect(() => {
    let cancelled = false
    client.GET('/dashboard').then(({ data }) => {
      if (!cancelled && data) setSummary(data as unknown as DashboardSummary)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!summary) return <p>Loading…</p>

  return (
    <>
      <p className="page-sub">Actual scenario, as of {summary.today}.</p>

      {/* Amber, not green — nothing succeeded here, it's a pending state
          asking for attention. Same banner ScheduledPage.tsx's own Phase
          4.3 write-up already ported, reusing the identical hook. */}
      {!!pendingCount && (
        <div className="flash flash-warn" style={{ marginBottom: '1.2rem' }}>
          <Link to="/app/staging">
            {pendingCount} {pendingCount === 1 ? 'entry' : 'entries'} waiting in Staging for your approval →
          </Link>
        </div>
      )}

      <div className="stat-row">
        <div className="stat-tile">
          <div className="stat-label">Net worth</div>
          <div className={`stat-value${isNeg(summary.net_worth) ? ' neg' : ''}`}>
            {formatMoneyOrDash(summary.net_worth)}
          </div>
          <Link className="quiet-link" to="/app/balance-sheet">Balance Sheet →</Link>
        </div>
        <div className="stat-tile">
          <div className="stat-label">{summary.month_label} income</div>
          <div className="stat-value">{formatMoneyOrDash(summary.mtd_income)}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">{summary.month_label} expenses</div>
          <div className="stat-value">{formatMoneyOrDash(summary.mtd_expenses)}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">{summary.month_label} net</div>
          <div className={`stat-value${isNeg(summary.mtd_net) ? ' neg' : ''}`}>
            {formatMoneyOrDash(summary.mtd_net)}
          </div>
          <Link className="quiet-link" to="/app/income-statement">Income Statement →</Link>
        </div>
      </div>

      <h2>Recent activity</h2>
      <table className="ledger">
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th className="num money money-first">Amount</th>
          </tr>
        </thead>
        <tbody>
          {summary.recent.length === 0 && (
            <tr>
              <td colSpan={3} className="dim">
                No entries yet. Post one from <Link className="quiet-link" to="/app/entries?new=1">+ New entry</Link>.
              </td>
            </tr>
          )}
          {summary.recent.map((e) => (
            <tr key={e.id}>
              <td className="mono dim">{formatDate(e.entry_date)}</td>
              <td className="activity-desc-cell">
                <span className="activity-desc">
                  {e.description}
                  {e.payee_name && <span className="dim small"> · {e.payee_name}</span>}
                </span>
                <FlowLabel row={e} />
              </td>
              <td className="num money money-first">{formatMoneyOrDash(e.total_debits)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {summary.recent.length > 0 && (
        <p><Link className="quiet-link" to="/app/entries">View full journal →</Link></p>
      )}

      <h2 style={{ marginTop: '2rem' }}>Upcoming transactions</h2>
      <table className="ledger">
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th className="num money money-first">Amount</th>
          </tr>
        </thead>
        <tbody>
          {summary.upcoming.length === 0 && (
            <tr>
              <td colSpan={3} className="dim">
                No upcoming scheduled transactions. Set one up from{' '}
                <Link className="quiet-link" to="/app/scheduled">Scheduled Entries</Link>.
              </td>
            </tr>
          )}
          {summary.upcoming.map((e) => (
            <tr key={e.id}>
              <td className="mono dim">{formatDate(e.next_date)}</td>
              <td className="activity-desc-cell">
                <span className="activity-desc">
                  {e.description}
                  {e.payee_name && <span className="dim small"> · {e.payee_name}</span>}
                </span>
                <FlowLabel row={e} />
              </td>
              <td className="num money money-first">{formatMoneyOrDash(e.total_debits)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {summary.upcoming.length > 0 && (
        <p><Link className="quiet-link" to="/app/scheduled">View all scheduled →</Link></p>
      )}
    </>
  )
}
