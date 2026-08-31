import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { usePayees } from '../api/usePayees'
import { useScenarios } from '../api/useScenarios'
import { useTags } from '../api/useTags'
import { formatDate } from '../format/date'
import { formatMoney, formatMoneyOrDash, isZeroAmount } from '../format/money'
import { altLabel } from '../format/shortcut'
import Combobox from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import TagInput from '../widgets/TagInput'
import { useConfirm } from '../widgets/confirmContext'
import { usePostableAccounts } from '../widgets/usePostableAccounts'
import { useSelectMode } from '../widgets/useSelectMode'
import BulkTagsDialog from '../journal/BulkTagsDialog'
import DescriptionCell from '../journal/DescriptionCell'
import MemoCell from '../journal/MemoCell'
import StagingEditPanel from './StagingEditPanel'

// The Filterable transaction list archetype's second instance
// (docs/ARCHITECTURE.md, "Component archetypes"), review/approve for whatever's sitting in
// the one `is_staging` scenario. Reuses `JournalPage.tsx`'s own
// `DescriptionCell`/`MemoCell`/`BulkTagsDialog` unchanged — the routes
// they call (`/entries/{id}/edit-description`, `/entries/lines/{id}/edit-
// memo`, `/entries/tags`) work on any entry/line, posted or still pending,
// same parity `docs/ARCHITECTURE.md`'s own Staging section documents.
// `StagingEditPanel.tsx` is the one genuinely new piece — the per-entry
// "Edit" grid, relocated in place of an entry's `.staging-view` rather
// than a separate page.
//
// Real differences from the Journal's own filter-bar/list shape, not a
// shared component between the two pages (the UI-consistency audit
// already settled this: "already the target shape; no change proposed"):
// Scenario here filters on each entry's own *target* scenario (where it
// lands once approved — `target_scenario`, the one filter field with no
// Journal equivalent), not the scenario it's posted in (every row here
// already shares the one real Staging scenario). No hide-reversed
// checkbox (a still-pending entry can't be a reversal), no entry_id/
// account/payee "Showing only..." banners (nothing links into Staging
// with those query params the way a report drills into the Journal), no
// Export/pager (`list_pending` is never paginated). Select/Edit tags are
// the same mechanism as the Journal's; Approve/Reject replace Reverse,
// and stay visible-but-disabled throughout rather than select-only, so
// a person can see what those two actions do without first discovering
// Select.
interface StagingLine {
  id: number
  debit: string
  credit: string
  memo: string | null
  account_code: string
  account_name: string
}

interface StagingEntry {
  id: string
  entry_date: string
  description: string
  reference: string | null
  payee_name: string | null
  target_scenario_code: string | null
  schedule_description: string | null
  import_filename: string | null
  import_date: string | null
  total_debits: string
  lines: StagingLine[]
  tags: string[]
}

interface StagingResult {
  entries: StagingEntry[]
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// Same filter fragment as JournalPage.tsx's own — forked, not shared,
// matching `repository.py`'s own "forks modules/entries/repository.py's
// shared filter fragments rather than importing them" call for the
// identical reason (a vertical slice/screen should be deletable on its
// own).
const AMOUNT_OPS: Record<string, string> = {
  gte: '≥ at least',
  lte: '≤ at most',
  gt: '> more than',
  lt: '< less than',
  eq: '= exactly',
  between: 'between',
}

export default function StagingPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const targetScenario = searchParams.get('target_scenario') || ''
  const dateFrom = searchParams.get('date_from') || ''
  const dateTo = searchParams.get('date_to') || ''
  const qtextParam = searchParams.get('qtext') || ''
  const tags = searchParams.get('tags') || ''
  const account = searchParams.get('account') || ''
  const payee = searchParams.get('payee') || ''
  const amountOp = searchParams.get('amount_op') || ''
  const amountValueParam = searchParams.get('amount_value') || ''
  const amountValue2Param = searchParams.get('amount_value2') || ''

  // Same "free-typed fields only commit to the URL on a real submit"
  // carve-out as JournalPage.tsx's own — see its comment for the full
  // reasoning.
  const [qtext, setQtext] = useState(qtextParam)
  const [amountValue, setAmountValue] = useState(amountValueParam)
  const [amountValue2, setAmountValue2] = useState(amountValue2Param)
  useEffect(() => setQtext(qtextParam), [qtextParam])
  useEffect(() => setAmountValue(amountValueParam), [amountValueParam])
  useEffect(() => setAmountValue2(amountValue2Param), [amountValue2Param])

  const hasFilters = !!(targetScenario || dateFrom || dateTo || qtextParam || tags || account || payee || amountOp)

  function buildParams(overrides: Record<string, string>): URLSearchParams {
    const current: Record<string, string> = {
      target_scenario: targetScenario, date_from: dateFrom, date_to: dateTo, qtext, tags, account, payee,
      amount_op: amountOp, amount_value: amountValue, amount_value2: amountValue2,
    }
    const merged = { ...current, ...overrides }
    const next = new URLSearchParams()
    for (const [k, v] of Object.entries(merged)) if (v) next.set(k, v)
    return next
  }

  function applyFilters(overrides: Record<string, string>) {
    setSearchParams(buildParams(overrides))
  }

  const [result, setResult] = useState<StagingResult | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null)

  const stagingQuery = {
    date_from: dateFrom, date_to: dateTo, qtext: qtextParam, tags, account, payee,
    amount_op: amountOp, amount_value: amountValueParam, amount_value2: amountValue2Param,
    target_scenario: targetScenario,
  }

  // `reload()` (user-triggered mutations) vs. the `cancelled`-guarded
  // filter effect below — same split, same reasoning, as JournalPage.
  // tsx's own two fetch paths.
  const reload = useCallback(async () => {
    const { data } = await client.GET('/staging', { params: { query: stagingQuery } })
    if (data) setResult(data as unknown as StagingResult)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, qtextParam, tags, account, payee, amountOp, amountValueParam, amountValue2Param, targetScenario])

  useEffect(() => {
    let cancelled = false
    client.GET('/staging', { params: { query: stagingQuery } }).then(({ data }) => {
      if (!cancelled && data) setResult(data as unknown as StagingResult)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, qtextParam, tags, account, payee, amountOp, amountValueParam, amountValue2Param, targetScenario])

  const scenarios = useScenarios()
  const postableAccounts = usePostableAccounts(scenarios)
  const payees = usePayees()
  const tagOptions = useTags()
  const allTagNames = (tagOptions ?? []).map((t) => t.name)

  const activePayees = (payees ?? []).filter((p) => p.is_active)
  const filterPayeeNames = (payees ?? []).map((p) => p.name)
  // Every non-staging scenario is a legal approval destination.
  const targetScenarios = (scenarios ?? []).filter((s) => !s.is_staging)

  const selectAllRef = useRef<HTMLInputElement>(null)
  const entryIds = (result?.entries ?? []).map((e) => e.id)
  const select = useSelectMode<string>(entryIds, selectAllRef)
  const confirm = useConfirm()

  const checkedEntries = (result?.entries ?? []).filter((e) => select.checkedIds.has(e.id))
  const [tagsDialogOpen, setTagsDialogOpen] = useState(false)

  // Approve is the one action with no undo through this screen again
  // (fixable only with Reverse from the Journal, once posted); bulk
  // Reject is a permanent delete, same `danger` styling as its per-entry
  // sibling.
  async function handleApprove() {
    const ids = Array.from(select.checkedIds)
    if (ids.length === 0) return
    const msg =
      ids.length === 1
        ? "Approve this entry? It'll be posted for real — Reject won't be able to undo it anymore, only Reverse."
        : `Approve these ${ids.length} entries? They'll be posted for real — Reject won't be able to undo them anymore, only Reverse.`
    const ok = await confirm(msg)
    if (!ok) return
    const { data, error } = await client.POST('/staging/approve', { body: { entry_ids: ids } })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not approve entries') })
      return
    }
    const body = data as unknown as { approved: string[]; errors: string[] }
    select.toggleSelectMode()
    setFlash({
      ok:
        `Approved ${body.approved.length} ${body.approved.length === 1 ? 'entry' : 'entries'}` +
        (body.errors.length ? `; ${body.errors.length} failed` : ''),
    })
    await reload()
  }

  async function handleReject() {
    const ids = Array.from(select.checkedIds)
    if (ids.length === 0) return
    const msg =
      ids.length === 1
        ? 'Reject and permanently delete this entry? This cannot be undone.'
        : `Reject and permanently delete these ${ids.length} entries? This cannot be undone.`
    const ok = await confirm(msg, { danger: true })
    if (!ok) return
    const { data, error } = await client.POST('/staging/reject', { body: { entry_ids: ids } })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not reject entries') })
      return
    }
    const body = data as unknown as { rejected: string[]; errors: string[] }
    select.toggleSelectMode()
    setFlash({
      ok:
        `Rejected ${body.rejected.length} ${body.rejected.length === 1 ? 'entry' : 'entries'}` +
        (body.errors.length ? `; ${body.errors.length} failed` : ''),
    })
    await reload()
  }

  // Alt+A/Alt+R for Approve/Reject. Re-registered each render so it
  // always closes over the current selection, same reasoning
  // JournalPage.tsx's own Alt+R handler gives.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!e.altKey || select.checkedIds.size === 0) return
      if (e.code === 'KeyA') {
        e.preventDefault()
        handleApprove()
      } else if (e.code === 'KeyR') {
        e.preventDefault()
        handleReject()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  })

  if (result === null || scenarios === null || postableAccounts === null || payees === null) {
    return <p>Loading…</p>
  }

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#staging" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

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
                ...targetScenarios.map((s) => ({ value: s.code, label: s.code })),
              ]}
              value={targetScenario}
              onChange={(v) => applyFilters({ target_scenario: v })}
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
            <Link className="button-link" to="/app/staging">
              Clear filters
            </Link>
          ) : (
            <a className="button-link disabled" aria-disabled="true">
              Clear filters
            </a>
          )}
        </div>
      </form>

      {result.entries.length === 0 ? (
        hasFilters ? (
          <p className="dim">No staged entries match these filters — use Clear filters above to see everything pending.</p>
        ) : (
          <p className="dim">
            No staged entries right now. Once a scheduled entry comes due or a CSV import lands, they&rsquo;ll show up
            here waiting for you to review and approve.
          </p>
        )
      ) : (
        <>
          <p className="bar" style={{ alignItems: 'center' }}>
            <button type="button" className="quiet" onClick={select.toggleSelectMode}>
              {select.selectMode ? 'Deselect' : 'Select'}
            </button>
            <label className="checkline select-only">
              <input ref={selectAllRef} type="checkbox" onChange={select.toggleSelectAll} /> select all
            </label>
            <button type="button" className="quiet" disabled={select.checkedIds.size === 0} onClick={() => setTagsDialogOpen(true)}>
              Edit tags
            </button>
            <button type="button" disabled={select.checkedIds.size === 0} onClick={handleApprove}>
              Approve ({altLabel('A')})
            </button>
            <button type="button" className="quiet" disabled={select.checkedIds.size === 0} onClick={handleReject}>
              Reject ({altLabel('R')})
            </button>
            <Link className="button-link" to="/app/staging/duplicates" style={{ marginLeft: 'auto' }}>
              Find duplicates
            </Link>
          </p>

          {result.entries.map((e) => (
            <details className="entry entry-staging" key={e.id}>
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
                <span>
                  <DescriptionCell
                    entryId={e.id}
                    description={e.description}
                    onSaved={(value) =>
                      setResult((r) => r && { ...r, entries: r.entries.map((x) => (x.id === e.id ? { ...x, description: value } : x)) })
                    }
                  />
                  {e.payee_name && <span className="dim small">· {e.payee_name}</span>}
                  <span className="badge">→ {e.target_scenario_code || 'ACTUAL'}</span>
                </span>
                <span className="num mono">{formatMoneyOrDash(e.total_debits)}</span>
                <span />
              </summary>
              <div className="lines" data-entry-id={e.id}>
                {editingEntryId === e.id ? (
                  <StagingEditPanel
                    key={e.id}
                    entryId={e.id}
                    scenarios={scenarios}
                    postableByScenario={postableAccounts.byScenario}
                    payees={activePayees}
                    allTags={allTagNames}
                    onSaved={() => {
                      setEditingEntryId(null)
                      setFlash({ ok: `Entry #${e.id} saved` })
                      reload()
                    }}
                    onCancel={() => setEditingEntryId(null)}
                  />
                ) : (
                  <div className="staging-view">
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
                    <p style={{ marginTop: '0.6rem', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                      <button type="button" className="quiet" onClick={() => setEditingEntryId(e.id)}>
                        Edit
                      </button>
                      {e.schedule_description ? (
                        <span className="dim small italic">Created from schedule &lsquo;{e.schedule_description}&rsquo;</span>
                      ) : e.import_filename ? (
                        <span className="dim small italic">
                          Imported from file &lsquo;{e.import_filename}&rsquo; on {formatDate(e.import_date)}
                        </span>
                      ) : null}
                    </p>
                  </div>
                )}
              </div>
            </details>
          ))}
        </>
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
