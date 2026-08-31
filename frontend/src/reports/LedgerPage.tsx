import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatDate } from '../format/date'
import { formatMoney } from '../format/money'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'

// The only report screen with a genuinely different layout — a wrapped
// grid of small T-account cards (Date | Debit | Credit | Date), one per
// account with activity, not one wide report table. No account
// hierarchy at all (flat cards, no useCollapsibleTree — same reasoning
// Cash Flow's own comment gives).
interface CardRow {
  debit_date: string | null
  debit: string | number | null
  credit: string | number | null
  credit_date: string | null
}

interface Card {
  code: string
  name: string
  rows: CardRow[]
  total_debit: string | number | null
  total_credit: string | number | null
  link_date_from: string
}

interface Group {
  label: string
  rows: Card[]
}

interface LedgerResult {
  grouped: Group[]
  as_of: string
  month_start: string
  scenario: string
  zeros: number
  raw: number
  prev_as_of: string
  next_as_of: string
  today: string
}

export default function LedgerPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const [result, setResult] = useState<LedgerResult | null>(null)

  const scenario = searchParams.get('scenario') || 'ACTUAL'
  const asOf = searchParams.get('as_of') || ''
  const zeros = searchParams.get('zeros') === '1'
  const raw = searchParams.get('raw') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/reports/ledger', {
        params: { query: { scenario, as_of: asOf, zeros: zeros ? 1 : 0, raw: raw ? 1 : 0 } },
      })
      .then(({ data }) => {
        if (!cancelled && data) setResult(data as unknown as LedgerResult)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, asOf, zeros, raw])

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

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          {asOf ? `As of ${asOf}` : 'Through today'} · scenario <span className="mono">{scenario}</span>
          {!raw && ' · simulated monthly close for Income/Expense'}
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
      ) : result.grouped.length === 0 ? (
        <p className="dim">
          No activity in {scenario} this month.{' '}
          {/* A real <Link> (an <a> under the hood), not a <button> —
              .button-link's CSS targets `a.button-link` specifically
              (index.css), the exact bug class the 2026-08-30 QA pass
              already found and fixed for Journal's own "Clear filters".
              Plain quiet-link styling here instead: it's inline prose,
              not a standalone action button. */}
          <Link className="quiet-link" to={`?${pageParams({ zeros: '1' })}`}>
            Show accounts with no activity
          </Link>
        </p>
      ) : (
        result.grouped.map((g) => (
          <section className="t-account-section" key={g.label}>
            <h2 className="t-section-label">{g.label}</h2>
            <div className="t-account-grid">
              {g.rows.map((a) => (
                <TAccountCard key={a.code} card={a} scenario={result.scenario} asOf={result.as_of} />
              ))}
            </div>
          </section>
        ))
      )}
    </>
  )
}

// ledger.html's own two link patterns: the caption drills through to
// the account's whole window (link_date_from..as_of — link_date_from is
// month_start for a flow account outside raw mode, "" otherwise, same
// as Trial Balance's is_flow logic but computed server-side here since
// Card carries it directly), and each individual debit/credit cell
// drills through to its own single day (cell_link — date_from and
// date_to both equal that one row's date, only linked when a value is
// actually there).
function cellLink(scenario: string, code: string, date: string) {
  return `/app/entries?scenario=${encodeURIComponent(scenario)}&date_from=${date}&date_to=${date}&account=${encodeURIComponent(code)}`
}

function TAccountCard({ card, scenario, asOf }: { card: Card; scenario: string; asOf: string }) {
  return (
    <table className="ledger t-account">
      <caption>
        <Link className="amount-link"
              to={`/app/entries?scenario=${encodeURIComponent(scenario)}&date_from=${card.link_date_from}&date_to=${asOf}&account=${encodeURIComponent(card.code)}`}>
          {card.code} · {card.name}
        </Link>
      </caption>
      <thead>
        <tr>
          <th className="dim small">Date</th>
          <th className="num money money-first">Debit</th>
          <th className="num money money-last t-divider">Credit</th>
          <th className="dim small">Date</th>
        </tr>
      </thead>
      <tbody>
        {card.rows.map((r, i) => (
          <tr key={i}>
            <td className="dim small">{r.debit_date ? formatDate(r.debit_date) : ''}</td>
            <td className="num money money-first">
              {r.debit ? (
                <Link className="amount-link" to={cellLink(scenario, card.code, r.debit_date!)}>{formatMoney(r.debit)}</Link>
              ) : ''}
            </td>
            <td className="num money money-last t-divider">
              {r.credit ? (
                <Link className="amount-link" to={cellLink(scenario, card.code, r.credit_date!)}>{formatMoney(r.credit)}</Link>
              ) : ''}
            </td>
            <td className="dim small">{r.credit_date ? formatDate(r.credit_date) : ''}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="grand">
          <td></td>
          <td className="num money money-first">{card.total_debit ? formatMoney(card.total_debit) : ''}</td>
          <td className="num money t-divider">{card.total_credit ? formatMoney(card.total_credit) : ''}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>
  )
}
