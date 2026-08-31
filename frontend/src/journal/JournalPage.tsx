import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useAccounts } from '../api/useAccounts'
import client from '../api/client'
import { usePayees } from '../api/usePayees'
import { useScenarios } from '../api/useScenarios'
import { useTags } from '../api/useTags'
import { useTemplates } from '../api/useTemplates'
import { formatDate } from '../format/date'
import { formatMoney, formatMoneyOrDash, isZeroAmount } from '../format/money'
import { altLabel } from '../format/shortcut'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import TagInput from '../widgets/TagInput'
import { useConfirm } from '../widgets/confirmContext'
import { usePostableAccounts } from '../widgets/usePostableAccounts'
import { useSelectMode } from '../widgets/useSelectMode'
import BulkTagsDialog from './BulkTagsDialog'
import DescriptionCell from './DescriptionCell'
import MemoCell from './MemoCell'
import NewEntryPanel from './NewEntryPanel'

// The Journal — the biggest single screen in the app. `NewEntryPanel.tsx`/
// `EntryGrid.tsx` own the "+ New entry" form; this owns the filter bar,
// the list itself, Select mode + Reverse + Edit tags, and export/pager.
//
// GET /entries's own response is a plain `dict` (`modules/entries/
// router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}` — cast through these local interfaces
// instead.
interface EntryLine {
  id: number
  debit: string
  credit: string
  memo: string | null
  account_code: string
  account_name: string
}

interface Entry {
  id: string
  entry_date: string
  description: string
  reference: string | null
  reverses_entry_id: string | null
  scenario_code: string
  posted_by: string | null
  payee_name: string | null
  total_debits: string
  total_credits: string
  reversed_by: string | null
  lines: EntryLine[]
  tags: string[]
}

interface EntriesResult {
  entries: Entry[]
  page: number
  page_size: number
  has_next: boolean
  has_prev: boolean
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

const AMOUNT_OPS: Record<string, string> = {
  gte: '≥ at least',
  lte: '≤ at most',
  gt: '> more than',
  lt: '< less than',
  eq: '= exactly',
  between: 'between',
}

export default function JournalPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const scenario = searchParams.get('scenario') || ''
  const dateFrom = searchParams.get('date_from') || ''
  const dateTo = searchParams.get('date_to') || ''
  const qtextParam = searchParams.get('qtext') || ''
  const tags = searchParams.get('tags') || ''
  const account = searchParams.get('account') || ''
  const payee = searchParams.get('payee') || ''
  const amountOp = searchParams.get('amount_op') || ''
  const amountValueParam = searchParams.get('amount_value') || ''
  const amountValue2Param = searchParams.get('amount_value2') || ''
  const hideReversed = searchParams.get('hide_reversed') === '1'
  const entryId = searchParams.get('entry_id') || ''
  const page = Math.max(Number(searchParams.get('page') || '1'), 1)

  // Free-typed fields only commit to the URL (and therefore refetch) on
  // a real form submit — Enter in any field, or the Search icon's own
  // click; every other control below applies immediately on change,
  // since deferring those the same way would just make filtering feel
  // laggy for no typing-debounce benefit. Resynced from the URL whenever
  // it changes out from under them (Clear filters, a one-field "clear"
  // link) via the effects right below.
  const [qtext, setQtext] = useState(qtextParam)
  const [amountValue, setAmountValue] = useState(amountValueParam)
  const [amountValue2, setAmountValue2] = useState(amountValue2Param)
  useEffect(() => setQtext(qtextParam), [qtextParam])
  useEffect(() => setAmountValue(amountValueParam), [amountValueParam])
  useEffect(() => setAmountValue2(amountValue2Param), [amountValue2Param])

  const hasFilters = !!(
    scenario || dateFrom || dateTo || qtextParam || tags || account || payee || amountOp || hideReversed || entryId
  )

  // A real navigation-equivalent (`push`, not `replace`) for every one
  // of these — unlike TrialBalancePage.tsx's own `As of` field, a
  // browser-history entry per Journal filter change is exactly the
  // parity this needs (Back should step through filter states, not
  // leave the Journal entirely), not something to avoid.
  function buildParams(overrides: Record<string, string>): URLSearchParams {
    const current: Record<string, string> = {
      scenario, date_from: dateFrom, date_to: dateTo, qtext, tags, account, payee,
      amount_op: amountOp, amount_value: amountValue, amount_value2: amountValue2,
      hide_reversed: hideReversed ? '1' : '', entry_id: entryId,
    }
    const merged = { ...current, ...overrides }
    const next = new URLSearchParams()
    for (const [k, v] of Object.entries(merged)) if (v) next.set(k, v)
    return next
  }

  function applyFilters(overrides: Record<string, string>) {
    setSearchParams(buildParams(overrides))
  }

  const [result, setResult] = useState<EntriesResult | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  const entriesQuery = {
    scenario, date_from: dateFrom, date_to: dateTo, qtext: qtextParam, tags, account, payee,
    amount_op: amountOp, amount_value: amountValueParam, amount_value2: amountValue2Param,
    hide_reversed: hideReversed ? 1 : 0, entry_id: entryId, page,
  }

  // `reload()` is the version every write handler below calls after its
  // own mutation lands (Reverse, bulk Edit tags) — always user-
  // triggered, so no unmounted-component race to guard against, same
  // reasoning `TagsPage.tsx`'s own `reload` gives. The *filter-driven*
  // fetch just below is a separate, `cancelled`-guarded effect instead
  // of routing through this — filter changes can fire in quick
  // succession (typing fast in Search, say), and only that path
  // actually needs to discard a response that's no longer the latest
  // request in flight.
  const reload = useCallback(async () => {
    const { data } = await client.GET('/entries', { params: { query: entriesQuery } })
    if (data) setResult(data as unknown as EntriesResult)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, dateFrom, dateTo, qtextParam, tags, account, payee, amountOp, amountValueParam, amountValue2Param, hideReversed, entryId, page])

  useEffect(() => {
    let cancelled = false
    client.GET('/entries', { params: { query: entriesQuery } }).then(({ data }) => {
      if (!cancelled && data) setResult(data as unknown as EntriesResult)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario, dateFrom, dateTo, qtextParam, tags, account, payee, amountOp, amountValueParam, amountValue2Param, hideReversed, entryId, page])

  const scenarios = useScenarios()
  const postableAccounts = usePostableAccounts(scenarios)
  const accounts = useAccounts()
  const payees = usePayees()
  const templates = useTemplates()
  const tagOptions = useTags()
  const allTagNames = (tagOptions ?? []).map((t) => t.name)

  const activePayees = (payees ?? []).filter((p) => p.is_active)
  const filterPayeeNames = (payees ?? []).map((p) => p.name)

  const accountRow = account ? accounts?.find((a) => a.code === account) : undefined
  const payeeRow = payee ? (payees ?? []).find((p) => p.name === payee) : undefined

  const selectAllRef = useRef<HTMLInputElement>(null)
  const entryIds = (result?.entries ?? []).map((e) => e.id)
  const select = useSelectMode<string>(entryIds, selectAllRef)
  const confirm = useConfirm()

  const checkedEntries = (result?.entries ?? []).filter((e) => select.checkedIds.has(e.id))
  const [tagsDialogOpen, setTagsDialogOpen] = useState(false)

  async function handleReverse() {
    const ids = Array.from(select.checkedIds)
    if (ids.length === 0) return
    const msg =
      ids.length === 1
        ? "Are you sure you want to post a reversal for this entry? You can't delete a posted entry, only reverse it."
        : `Are you sure you want to post a reversal for these ${ids.length} entries? You can't delete a posted entry, only reverse it.`
    const ok = await confirm(msg)
    if (!ok) return
    const { data, error } = await client.POST('/entries/reverse', { body: { entry_ids: ids } })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not reverse entries') })
      return
    }
    const body = data as unknown as { reversed: string[]; errors: string[] }
    select.toggleSelectMode()
    setFlash({
      ok:
        `Reversed ${body.reversed.length} ${body.reversed.length === 1 ? 'entry' : 'entries'}` +
        (body.errors.length ? `; ${body.errors.length} failed` : ''),
    })
    await reload()
  }

  // Alt+R for Reverse. Re-registered each render (cheap, a single
  // document listener) so it always closes
  // over the current selection rather than a stale one from mount.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey && e.code === 'KeyR' && select.checkedIds.size > 0) {
        e.preventDefault()
        handleReverse()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  })

  const exportQuery = buildParams({}).toString()

  if (result === null || scenarios === null || postableAccounts === null || payees === null || templates === null) {
    return <p>Loading…</p>
  }

  return (
    <>
      <div className="page-head">
        {/* No "Back to report" link: that would only make sense arriving
            via a drill-through link from another report, and nothing in
            the app produces one yet — add this once a report actually
            links here with a `back=` param set. */}
        <Link to="/app/help#journal" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      {accountRow && (
        <p className="page-sub">
          Showing only postings to <span className="mono">{accountRow.code}</span> {accountRow.name} —{' '}
          <button type="button" className="quiet-link" onClick={() => applyFilters({ account: '' })}>
            clear
          </button>
        </p>
      )}
      {payeeRow && (
        <p className="page-sub">
          Showing only entries for payee <span className="mono">{payeeRow.name}</span> —{' '}
          <button type="button" className="quiet-link" onClick={() => applyFilters({ payee: '' })}>
            clear
          </button>
        </p>
      )}
      {entryId && (
        <p className="page-sub">
          Showing only entry <span className="mono">#{entryId}</span> —{' '}
          <button type="button" className="quiet-link" onClick={() => applyFilters({ entry_id: '' })}>
            clear
          </button>
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          applyFilters({ qtext, amount_value: amountValue, amount_value2: amountValue2 })
        }}
      >
        <div className="bar">
          <label className="field">
            Scenario
            <Combobox
              options={[
                { value: '', label: 'All' },
                ...scenarios.filter((s) => !s.is_staging).map((s) => ({ value: s.code, label: s.code })),
              ]}
              value={scenario}
              onChange={(v) => applyFilters({ scenario: v })}
            />
          </label>
          <label className="field">
            From
            <DatePicker value={dateFrom} onChange={(v) => applyFilters({ date_from: v })} />
          </label>
          <label className="field">
            To
            <DatePicker value={dateTo} onChange={(v) => applyFilters({ date_to: v })} />
          </label>
          <label className="field">
            Search
            <span className="search-field">
              <input
                type="text"
                className="search-input"
                placeholder="Description, ref."
                value={qtext}
                onChange={(e) => setQtext(e.target.value)}
              />
              <button type="submit" className="search-submit" aria-label="Search">
                <span className="search-icon" />
              </button>
            </span>
          </label>
          <label className="field" style={{ flex: 1, minWidth: '14rem' }}>
            Tags
            <TagInput
              value={tags}
              onChange={(v) => applyFilters({ tags: v })}
              suggestions={allTagNames}
              creatable={false}
              placeholder="Filter by tag…"
            />
          </label>
          <label className="field" style={{ minWidth: '12rem' }}>
            Account
            <Combobox
              options={[
                { value: '', label: 'All' },
                ...postableAccounts.forPickers.map((a) => ({ value: a.code, label: `${a.code} · ${a.name}` })),
              ]}
              value={account}
              onChange={(v) => applyFilters({ account: v })}
            />
          </label>
          <label className="field" style={{ minWidth: '10rem' }}>
            Payee
            <Combobox
              options={[{ value: '', label: 'All' }, ...filterPayeeNames.map((name) => ({ value: name, label: name }))]}
              value={payee}
              onChange={(v) => applyFilters({ payee: v })}
            />
          </label>
          <label className="field">
            Amount
            <Combobox
              options={[
                { value: '', label: 'Any' },
                ...Object.entries(AMOUNT_OPS).map(([op, label]) => ({ value: op, label })),
              ]}
              value={amountOp}
              onChange={(v) => applyFilters({ amount_op: v })}
            />
          </label>
          {amountOp && (
            <label className="field" style={{ flex: 'none' }}>
              &nbsp;
              <span className="amount-range">
                <input
                  type="text"
                  className="amount"
                  inputMode="decimal"
                  value={amountValue}
                  onChange={(e) => setAmountValue(e.target.value)}
                  placeholder={amountOp === 'between' ? 'Min' : 'Value'}
                  style={{ width: '7rem' }}
                />
                {amountOp === 'between' && (
                  <>
                    <span className="dim small">and</span>
                    <input
                      type="text"
                      className="amount"
                      inputMode="decimal"
                      value={amountValue2}
                      onChange={(e) => setAmountValue2(e.target.value)}
                      placeholder="Max"
                      style={{ width: '7rem' }}
                    />
                  </>
                )}
              </span>
            </label>
          )}
          {hasFilters ? (
            // A real <a> (via <Link>), not <button> — .button-link's CSS
            // targets `a.button-link` specifically (see index.css); a
            // <button> with this class instead falls through to the
            // bare `button` element rule and picks up filled button
            // chrome it was never meant to have.
            <Link className="button-link" to="/app/entries">
              Clear filters
            </Link>
          ) : (
            <a className="button-link disabled" aria-disabled="true">
              Clear filters
            </a>
          )}
        </div>
      </form>

      <div className="bar" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <p className="bar" style={{ marginBottom: 0 }}>
          <button type="button" className="quiet" onClick={select.toggleSelectMode}>
            {select.selectMode ? 'Deselect' : 'Select'}
          </button>
          <label className="checkline select-only">
            <input ref={selectAllRef} type="checkbox" onChange={select.toggleSelectAll} /> select all
          </label>
          <button type="button" className="quiet" disabled={select.checkedIds.size === 0} onClick={() => setTagsDialogOpen(true)}>
            Edit tags
          </button>
          <button type="button" disabled={select.checkedIds.size === 0} onClick={handleReverse}>
            Reverse ({altLabel('R')})
          </button>
        </p>
        <span className="bar" style={{ marginBottom: 0 }}>
          <a className="quiet-link" href={`/entries/export.csv?${exportQuery}`}>
            Export CSV
          </a>
          <a className="quiet-link" href={`/entries/export.xlsx?${exportQuery}`}>
            Export XLSX
          </a>
        </span>
      </div>

      <p className="bar" style={{ alignItems: 'center' }}>
        <label className="checkline">
          <input
            type="checkbox"
            checked={hideReversed}
            onChange={(e) => applyFilters({ hide_reversed: e.target.checked ? '1' : '' })}
          />
          hide reversed/reversals
        </label>
      </p>

      <NewEntryPanel
        scenarios={scenarios}
        postableByScenario={postableAccounts.byScenario}
        payees={activePayees}
        templates={templates}
        allTags={allTagNames}
        defaultOpen={new URLSearchParams(window.location.search).get('new') === '1'}
        onPosted={(postedId) => {
          setFlash({ ok: `Entry #${postedId} posted` })
          reload()
        }}
      />

      {result.entries.length === 0 ? (
        <p className="dim">
          {hasFilters ? (
            <>
              No entries match these filters — use{' '}
              <Link className="quiet-link" to="/app/entries">
                Clear filters
              </Link>{' '}
              above to see everything posted.
            </>
          ) : (
            <>
              No entries yet. Post one from{' '}
              <button
                type="button"
                className="quiet-link"
                onClick={() => {
                  const details = document.getElementById('new-entry-panel') as HTMLDetailsElement | null
                  if (details) details.open = true
                }}
              >
                + New entry
              </button>{' '}
              above.
            </>
          )}
        </p>
      ) : (
        result.entries.map((e) => (
          <details className="entry entry-journal" key={e.id}>
            <summary>
              <label className="checkline select-only" onClick={(ev) => ev.stopPropagation()}>
                <input
                  type="checkbox"
                  className="entry-check"
                  checked={select.checkedIds.has(e.id)}
                  onChange={() => select.toggleChecked(e.id)}
                  onClick={(ev) => ev.stopPropagation()}
                />
              </label>
              <span className="mono dim">{formatDate(e.entry_date)}</span>
              <span className="mono dim">#{e.id}</span>
              <span>
                <DescriptionCell
                  entryId={e.id}
                  description={e.description}
                  onSaved={(value) =>
                    setResult((r) => r && { ...r, entries: r.entries.map((x) => (x.id === e.id ? { ...x, description: value } : x)) })
                  }
                />
                {e.payee_name && <span className="dim small">· {e.payee_name}</span>}
                {e.reference && <span className="dim small">[{e.reference}]</span>}
                {e.posted_by && <span className="dim small">— {e.posted_by}</span>}
              </span>
              {/* Every per-entry badge — reversal links and real tags alike
                  — lives in this one trailing grid column (last "auto" in
                  .entry-journal summary's own template), right of the
                  description and before the amount, so none of them ever
                  compete with description text on the same line or push
                  the amount column around. Real <a>s (via <Link>), not
                  <button>s, for the reversal badges — .badge's CSS has no
                  button-specific override, so a <button class="badge">
                  falls through to the bare `button` element rule and
                  picks up filled accent chrome instead of the plain
                  outlined pill an `<a class="badge rev">` gets. Link's own
                  click handling already preventDefault()s on a plain
                  click before navigating, which is what stops
                  <summary>'s native toggle here — same mechanism
                  DescriptionCell's span relies on, no separate handler
                  needed. */}
              <span className="entry-tags">
                {e.reverses_entry_id && (
                  <Link className="badge rev" to={`?${buildParams({ entry_id: String(e.reverses_entry_id) }).toString()}`}>
                    reversal of #{e.reverses_entry_id}
                  </Link>
                )}
                {e.reversed_by && (
                  <Link className="badge rev" to={`?${buildParams({ entry_id: String(e.reversed_by) }).toString()}`}>
                    reversed by #{e.reversed_by}
                  </Link>
                )}
                {e.tags.map((t) => (
                  <Link
                    key={t}
                    className="badge tag"
                    to={`?${buildParams({ tags: t }).toString()}`}
                  >
                    {t}
                  </Link>
                ))}
              </span>
              <span className="num mono">{formatMoneyOrDash(e.total_debits)}</span>
            </summary>
            <div className="lines">
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th className="num money money-first">Debit</th>
                    <th className="num money">Credit</th>
                    <th>Memo</th>
                  </tr>
                </thead>
                <tbody>
                  {e.lines.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <span className="mono dim">{l.account_code}</span> {l.account_name}
                      </td>
                      <td className="num money money-first">{isZeroAmount(l.debit) ? '' : formatMoney(l.debit)}</td>
                      <td className="num money">{isZeroAmount(l.credit) ? '' : formatMoney(l.credit)}</td>
                      <MemoCell
                        lineId={l.id}
                        memo={l.memo}
                        onSaved={(value) =>
                          setResult(
                            (r) =>
                              r && {
                                ...r,
                                entries: r.entries.map((x) =>
                                  x.id !== e.id ? x : { ...x, lines: x.lines.map((ln) => (ln.id === l.id ? { ...ln, memo: value } : ln)) },
                                ),
                              },
                          )
                        }
                      />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))
      )}

      {(result.has_prev || result.has_next) && (
        <div className="pager">
          {result.has_prev ? (
            <Link to={`?${buildParams({ page: String(page - 1) }).toString()}`}>&larr; Newer</Link>
          ) : (
            <span className="dim">&larr; Newer</span>
          )}
          <span className="dim small">page {page}</span>
          {result.has_next ? (
            <Link to={`?${buildParams({ page: String(page + 1) }).toString()}`}>Older &rarr;</Link>
          ) : (
            <span className="dim">Older &rarr;</span>
          )}
        </div>
      )}

      <BulkTagsDialog
        open={tagsDialogOpen}
        entryIds={Array.from(select.checkedIds)}
        initialTags={Array.from(new Set(checkedEntries.flatMap((e) => e.tags)))}
        allTags={allTagNames}
        onClose={(changed) => {
          setTagsDialogOpen(false)
          if (changed) reload()
        }}
      />
    </>
  )
}
