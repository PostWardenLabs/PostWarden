import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { usePayees, type Payee } from '../api/usePayees'
import { useTags } from '../api/useTags'
import { formatMoney } from '../format/money'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import TagInput from '../widgets/TagInput'
import { useSelectMode } from '../widgets/useSelectMode'

// Ported from app/templates/staging_duplicates.html + app/static/
// staging-duplicates.js (Phase 4.5) — backend already done (Phase 1.6,
// `modules/staging/service.py::find_duplicate_groups`/`merge_
// duplicates`), frontend-only this phase, same as Staging/Budget before
// it. `UI_CONSISTENCY_AUDIT.md` §2a/§4b calls this screen "one real
// sibling" of the Filterable transaction list archetype (Journal,
// Staging) rather than a sixth archetype of its own — it borrows that
// family's per-entry conventions (`useSelectMode`, the same select-only
// checkbox mechanism) — but it isn't a filter-bar list itself: there's no
// filter form, no pagination, and rows are pre-grouped server-side by an
// exact (date, account, amount) fingerprint rather than user-chosen
// criteria. It's grouped like the Ledger report's own per-account
// sections (hence reusing `.duplicate-group`'s `.t-section-label`-style
// heading, not a `<details>` list), just over duplicate candidates
// instead of accounts.
//
// The one genuinely new piece of client-side machinery: a merge flow
// that's two sequential custom dialogs, neither of which fits
// `useConfirm()`'s plain message+OK/Cancel shape (`ConfirmDialog.tsx`) —
// ported as local state/JSX here rather than a shared widget, since nothing
// else in the app needs either shape:
//
//   1. A three-way "Proceed / Select remaining entries / Cancel" dialog,
//      shown only when the group being merged has an unchecked entry
//      left over (BACKLOG.md's own spec) — same `.confirm-overlay`/
//      `.confirm-modal` CSS `ConfirmDialog.tsx` already uses, with the
//      same initial-focus-on-Cancel and Tab-trap treatment applied here
//      by hand for its three buttons instead of two.
//   2. The merge-detail form itself (Description/Reference/Payee/Tags,
//      one memo field per line the survivor keeps) — same CSS again,
//      `.confirm-modal h3` heading style matching `BulkTagsDialog.tsx`'s
//      own "modal that shows a control, not a message" shape.
//
// Per-line memo defaults are pre-filled the same way `openMergeDetail`
// legacy-side did: the survivor's own memo if it has one, else the first
// non-blank memo found on the *matching* (account, amount) leg among the
// other checked entries — never a guess across a different leg, since
// matching account+amount is exactly what makes two legs "the same line"
// across duplicate entries.

interface DuplicateLine {
  id: number
  account_id: number
  amount: string | number
  memo: string | null
  account_code: string
  account_name: string
}

interface DuplicateEntry {
  id: string
  entry_date: string
  description: string
  reference: string | null
  payee_id: number | null
  payee_name: string | null
  lines: DuplicateLine[]
  tags: string[]
}

interface DuplicateGroup {
  label: string
  entry_date: string
  entries: DuplicateEntry[]
}

interface DuplicatesResult {
  groups: DuplicateGroup[]
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// The one Amount column here is the entry's total debit leg(s) — ported
// from staging_duplicates.html's own `e.lines | selectattr('amount',
// 'gt', 0) | sum(attribute='amount')`. Signed `amount` (positive debit,
// negative credit) is `find_duplicate_groups`'s own shape — see
// `repository.lines_for_entries_signed`'s docstring.
function debitTotal(entry: DuplicateEntry): number {
  return entry.lines.filter((l) => Number(l.amount) > 0).reduce((sum, l) => sum + Number(l.amount), 0)
}

// A small per-group tri-state "select all in this section" checkbox —
// same checked/indeterminate convention every other select-all in the
// app uses, just scoped to one group's own entries rather than the whole
// page. Its own tiny component (rather than inlined JSX) purely so the
// imperative `indeterminate` set (a DOM-only property, no React prop for
// it — see `useSelectMode.ts`'s own identical comment) has a natural
// effect to live in, keyed on this group's own counts.
function GroupSelectAll({ checkedCount, total, onToggle }: { checkedCount: number; total: number; onToggle: () => void }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.checked = checkedCount === total && total > 0
    el.indeterminate = checkedCount > 0 && checkedCount < total
  }, [checkedCount, total])
  return (
    <label className="checkline group-select-all select-only" style={{ marginLeft: '0.8rem' }}>
      <input ref={ref} type="checkbox" onChange={onToggle} /> select all in this section
    </label>
  )
}

// The three-way "Proceed / Select remaining entries / Cancel" dialog —
// state lives in the parent (a `resolve` closure captured on open, same
// Promise-returning shape `useConfirm()` gives its own single caller),
// this component only renders it. See this file's own top comment for
// why it's local rather than a second `useConfirm()`-style provider.
type ThreeWayChoice = 'cancel' | 'select' | 'proceed'

interface ThreeWayDialogProps {
  message: string
  onChoice: (choice: ThreeWayChoice) => void
}

function ThreeWayDialog({ message, onChoice }: ThreeWayDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const selectRef = useRef<HTMLButtonElement>(null)
  const proceedRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    cancelRef.current?.focus()
  }, [])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onChoice('cancel')
        return
      }
      if (e.key !== 'Tab') return
      const items = [cancelRef.current, selectRef.current, proceedRef.current].filter(
        (el): el is HTMLButtonElement => !!el,
      )
      e.preventDefault()
      const i = items.indexOf(document.activeElement as HTMLButtonElement)
      const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === items.length - 1 ? 0 : i + 1
      items[next]?.focus()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onChoice])

  return createPortal(
    <div className="confirm-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onChoice('cancel') }}>
      <div className="confirm-modal" role="alertdialog" aria-modal="true" aria-label="Merge duplicate entries">
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="quiet" onClick={() => onChoice('cancel')}>
            Cancel
          </button>
          <button ref={selectRef} type="button" className="quiet" onClick={() => onChoice('select')}>
            Select remaining entries
          </button>
          <button ref={proceedRef} type="button" className="confirm-ok" onClick={() => onChoice('proceed')}>
            Proceed
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function StagingDuplicatesPage() {
  const [result, setResult] = useState<DuplicatesResult | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  const reload = useCallback(async () => {
    const { data } = await client.GET('/staging/duplicates')
    if (data) setResult(data as unknown as DuplicatesResult)
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/staging/duplicates').then(({ data }) => {
      if (!cancelled && data) setResult(data as unknown as DuplicatesResult)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const payees = usePayees()
  const tagOptions = useTags()
  const allTagNames = (tagOptions ?? []).map((t) => t.name)

  const groups = result?.groups ?? []
  const allEntryIds = groups.flatMap((g) => g.entries.map((e) => e.id))
  // No page-level "select all" checkbox exists on this screen (only each
  // group's own, rendered by `GroupSelectAll` above) — this ref is never
  // attached to an element, which is fine: `useSelectMode`'s own
  // indeterminate-setting effect just no-ops when `.current` is null.
  const unusedSelectAllRef = useRef<HTMLInputElement>(null)
  const select = useSelectMode<string>(allEntryIds, unusedSelectAllRef)

  function checkedCountIn(group: DuplicateGroup): number {
    return group.entries.filter((e) => select.checkedIds.has(e.id)).length
  }

  function toggleGroupAll(group: DuplicateGroup) {
    const allChecked = group.entries.length > 0 && group.entries.every((e) => select.checkedIds.has(e.id))
    group.entries.forEach((e) => {
      const isChecked = select.checkedIds.has(e.id)
      if (allChecked ? isChecked : !isChecked) select.toggleChecked(e.id)
    })
  }

  const mergeableGroup = groups.find((g) => checkedCountIn(g) >= 2)

  // -- Three-way ask ------------------------------------------------------
  const [threeWay, setThreeWay] = useState<{ message: string; resolve: (c: ThreeWayChoice) => void } | null>(null)
  function askThreeWay(message: string): Promise<ThreeWayChoice> {
    return new Promise((resolve) => setThreeWay({ message, resolve }))
  }
  function settleThreeWay(choice: ThreeWayChoice) {
    threeWay?.resolve(choice)
    setThreeWay(null)
  }

  // -- Merge-detail dialog --------------------------------------------------
  interface MergeDetail {
    group: DuplicateGroup
    survivor: DuplicateEntry
    others: DuplicateEntry[]
  }
  const [mergeDetail, setMergeDetail] = useState<MergeDetail | null>(null)
  const [description, setDescription] = useState('')
  const [reference, setReference] = useState('')
  const [payeeId, setPayeeId] = useState('')
  const [tagsCsv, setTagsCsv] = useState('')
  const [memos, setMemos] = useState<Record<number, string>>({})
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // Payees created inline via the picker's own "+ Create" row — same
  // "merge into the options list, don't wait for a refetch" reasoning
  // `NewEntryPanel.tsx`'s own `createdPayees` gives.
  const [createdPayees, setCreatedPayees] = useState<Payee[]>([])
  const descriptionRef = useRef<HTMLInputElement>(null)

  // Same focus-and-select-on-open as legacy's own `descInput.focus();
  // descInput.select();` — the Description field is the one a user is
  // most likely to want to immediately overtype.
  useEffect(() => {
    if (mergeDetail) {
      descriptionRef.current?.focus()
      descriptionRef.current?.select()
    }
  }, [mergeDetail])

  // Escape cancels, same as every other overlay in the app — not gated
  // on `saving` (a save is a single fast POST; there's no meaningful
  // window where a user would hit Escape mid-save and expect it to be
  // ignored, and the backdrop-click handler below already carries that
  // same guard for the slower, accidental-click case).
  useEffect(() => {
    if (!mergeDetail) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setMergeDetail(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [mergeDetail])

  const payeeOptions: ComboboxOption[] = useMemo(
    () => [
      { value: '', label: 'None' },
      ...(payees ?? []).map((p) => ({ value: String(p.id), label: p.name })),
      ...createdPayees.map((p) => ({ value: String(p.id), label: p.name })),
    ],
    [payees, createdPayees],
  )

  async function createPayee(name: string): Promise<ComboboxOption | null> {
    const { data, error: err } = await client.POST('/payees/quick-create', { body: { name } })
    if (err || !data) return null
    const created = data as unknown as Payee
    setCreatedPayees((prev) => [...prev, created])
    return { value: String(created.id), label: created.name }
  }

  function findLeg(entry: DuplicateEntry, accountId: number, amount: string | number): DuplicateLine | undefined {
    return entry.lines.find((l) => l.account_id === accountId && Number(l.amount) === Number(amount))
  }

  function openMergeDetail(group: DuplicateGroup, checkedIds: string[]) {
    const entries = group.entries.filter((e) => checkedIds.includes(e.id))
    const survivor = entries[0]
    const others = entries.slice(1)

    const initialMemos: Record<number, string> = {}
    for (const line of survivor.lines) {
      let candidate = line.memo || ''
      if (!candidate) {
        for (const other of others) {
          const leg = findLeg(other, line.account_id, line.amount)
          if (leg?.memo) {
            candidate = leg.memo
            break
          }
        }
      }
      initialMemos[line.id] = candidate
    }

    const unionTags = new Set<string>()
    entries.forEach((e) => e.tags.forEach((t) => unionTags.add(t)))

    setDescription(survivor.description)
    setReference(survivor.reference || '')
    setPayeeId(survivor.payee_id != null ? String(survivor.payee_id) : '')
    setTagsCsv(Array.from(unionTags).join(','))
    setMemos(initialMemos)
    setDialogError(null)
    setMergeDetail({ group, survivor, others })
  }

  // Checking 2+ entries within one group enables Merge; clicking it
  // processes exactly one group per click — the first one (in document
  // order) with 2+ checked, same one-atomic-action-per-submit shape
  // Payees/Tags' own Merge already uses. If other duplicate groups
  // remain after this one merges, `reload()` recomputes them fresh —
  // Merge just works the same way again on whatever's left.
  async function handleMergeClick() {
    const group = mergeableGroup
    if (!group) return
    const checked = group.entries.filter((e) => select.checkedIds.has(e.id))
    const uncheckedCount = group.entries.length - checked.length
    let checkedIds = checked.map((e) => e.id)

    if (uncheckedCount > 0) {
      const noun = uncheckedCount === 1 ? 'entry' : 'entries'
      const verb = uncheckedCount === 1 ? 'is' : 'are'
      const choice = await askThreeWay(
        `Another ${noun} matching the same accounts, amounts and date ${verb} not being included. Are you sure you want to proceed?`,
      )
      if (choice === 'cancel') return
      if (choice === 'select') {
        group.entries.forEach((e) => {
          if (!select.checkedIds.has(e.id)) select.toggleChecked(e.id)
        })
        checkedIds = group.entries.map((e) => e.id)
      }
    }
    openMergeDetail(group, checkedIds)
  }

  async function saveMergeDetail() {
    if (!mergeDetail) return
    setSaving(true)
    setDialogError(null)
    const lineMemos: Record<string, string> = {}
    for (const [lineId, val] of Object.entries(memos)) lineMemos[lineId] = val.trim()
    const { data, error: err } = await client.POST('/staging/duplicates/merge', {
      body: {
        keep_id: mergeDetail.survivor.id,
        remove_ids: mergeDetail.others.map((o) => o.id),
        description: description.trim(),
        reference: reference.trim() || null,
        payee_id: payeeId ? Number(payeeId) : null,
        tags: tagsCsv,
        line_memos: lineMemos,
      },
    })
    setSaving(false)
    if (err) {
      setDialogError(errorDetail(err, 'Could not merge these entries'))
      return
    }
    const kept = (data as unknown as { kept_entry_id: string }).kept_entry_id
    setMergeDetail(null)
    setFlash({ ok: `Merged into #${kept}` })
    select.toggleSelectMode()
    await reload()
  }

  if (result === null || payees === null) {
    return <p>Loading…</p>
  }

  return (
    <>
      <div className="page-head">
        <p className="page-sub">Pending Staging entries that share the same accounts, amounts, and date</p>
        <Link to="/app/help#staging" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <p className="bar" style={{ alignItems: 'center' }}>
        <button type="button" className="quiet" onClick={select.toggleSelectMode}>
          {select.selectMode ? 'Deselect' : 'Select'}
        </button>
        <button type="button" disabled={!mergeableGroup} onClick={handleMergeClick}>
          Merge
        </button>
        <Link className="button-link" to="/app/staging">
          Back to Staging
        </Link>
      </p>

      {groups.length === 0 ? (
        <p className="dim">No potential duplicates right now — every pending Staging entry looks unique.</p>
      ) : (
        groups.map((group, i) => (
          <section className="duplicate-group" key={i}>
            <h2 className="duplicate-group-label">
              {group.label}
              <GroupSelectAll
                checkedCount={checkedCountIn(group)}
                total={group.entries.length}
                onToggle={() => toggleGroupAll(group)}
              />
            </h2>
            <table className="ledger">
              <thead>
                <tr>
                  <th className="select-only" />
                  <th>Description</th>
                  <th>Reference</th>
                  <th>Payee</th>
                  <th>Tags</th>
                  <th className="num money">Amount</th>
                </tr>
              </thead>
              <tbody>
                {group.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="select-only">
                      <input
                        type="checkbox"
                        className="dup-check"
                        checked={select.checkedIds.has(e.id)}
                        onChange={() => select.toggleChecked(e.id)}
                      />
                    </td>
                    <td>{e.description}</td>
                    <td className="dim">{e.reference || ''}</td>
                    <td className="dim">{e.payee_name || ''}</td>
                    <td className="dim small">{e.tags.join(', ')}</td>
                    <td className="num money">{formatMoney(debitTotal(e))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))
      )}

      {threeWay && <ThreeWayDialog message={threeWay.message} onChoice={settleThreeWay} />}

      {mergeDetail &&
        createPortal(
          <div
            className="confirm-overlay"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget && !saving) setMergeDetail(null)
            }}
          >
            <div className="confirm-modal" role="dialog" aria-label="Merge duplicate entries">
              <h3>Merge {mergeDetail.others.length + 1} entries</h3>

              {dialogError && <div className="flash flash-err">{dialogError}</div>}

              <label className="field" style={{ marginTop: '0.6rem' }}>
                Description
                <input
                  ref={descriptionRef}
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <label className="field" style={{ marginTop: '0.6rem' }}>
                Reference
                <input type="text" value={reference} onChange={(e) => setReference(e.target.value)} />
              </label>
              <label className="field" style={{ marginTop: '0.6rem' }}>
                Payee
                <Combobox options={payeeOptions} value={payeeId} onChange={setPayeeId} onCreate={createPayee} />
              </label>
              <label className="field" style={{ marginTop: '0.6rem' }}>
                Tags
                <TagInput value={tagsCsv} onChange={setTagsCsv} suggestions={allTagNames} placeholder="Add a tag…" />
              </label>

              {mergeDetail.survivor.lines.map((line) => (
                <label className="field" style={{ marginTop: '0.6rem' }} key={line.id}>
                  {`Memo — ${line.account_code} ${line.account_name}`}
                  <input
                    type="text"
                    value={memos[line.id] ?? ''}
                    onChange={(e) => setMemos((prev) => ({ ...prev, [line.id]: e.target.value }))}
                  />
                </label>
              ))}

              <div className="confirm-actions" style={{ marginTop: '1.1rem' }}>
                <button type="button" className="quiet" onClick={() => setMergeDetail(null)} disabled={saving}>
                  Cancel
                </button>
                <button type="button" className="confirm-ok" onClick={saveMergeDetail} disabled={saving}>
                  Merge
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
