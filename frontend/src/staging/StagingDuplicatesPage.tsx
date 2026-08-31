import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { usePayees, type Payee } from '../api/usePayees'
import { useTags } from '../api/useTags'
import { formatMoneyOrDash } from '../format/money'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import TagInput from '../widgets/TagInput'
import { useSelectMode } from '../widgets/useSelectMode'

// Backed by `modules/staging/service.py::find_duplicate_groups`/`merge_
// duplicates`. `UI_CONSISTENCY_AUDIT.md` §2a/§4b calls this screen "one real
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
// Merge, clicked once, processes every group that currently has 2+
// entries checked — not just the first one (BACKLOG.md's own follow-up
// ask, after the first pass only ever merged one group per click). Each
// group's own checked entries are independent staging rows, so a merge
// in one group can never invalidate another group's own fingerprint —
// safe to compute every group's merge plan up front, off one snapshot of
// `groups`/`checkedIds`, and fire them without waiting on a `reload()`
// in between.
//
// Within a group, a merge only ever needs a person's judgment when its
// checked entries actually disagree on Description/Reference/Payee/a
// line's Memo — two custom dialogs cover that, neither fitting
// `useConfirm()`'s plain message+OK/Cancel shape (`ConfirmDialog.tsx`):
//
//   1. A three-way "Proceed / Select remaining entries / Cancel" dialog,
//      shown only when a group being merged has an unchecked entry left
//      over (BACKLOG.md's own spec) — same `.confirm-overlay`/
//      `.confirm-modal` CSS `ConfirmDialog.tsx` already uses, with the
//      same initial-focus-on-Cancel and Tab-trap treatment applied here
//      by hand for its three buttons instead of two.
//   2. The merge-detail form (Description/Reference/Payee/Tags, one
//      memo field per line the survivor keeps) — same CSS again,
//      `.confirm-modal h3` heading style matching `BulkTagsDialog.tsx`'s
//      own "modal that shows a control, not a message" shape. Skipped
//      entirely — no prompt at all — whenever a group's checked entries
//      already agree on every field (`allFieldsMatch` below): there's
//      nothing to choose between. When they don't agree, "automatically
//      assign fields" (a page-level toggle) decides whether this dialog
//      shows at all: on, every disagreement is resolved by
//      `autoAssignFields`'s own rule (one entry has it and the other
//      doesn't → use the one that does; both have it → use whichever
//      value is longer) with no prompt; off, the dialog opens — still
//      pre-filled with that same `autoAssignFields` guess, just editable
//      — one at a time for however many groups actually need it, via
//      `dialogQueue`.
//
// Tags are never part of "do the fields agree" or the auto-assign rule
// above — a tag set only ever needs a union (whatever's on any checked
// entry ends up on the merged one), which is unambiguous regardless of
// how many entries agree, so it's computed the same way in every path
// below rather than threaded through the match/auto-assign logic at all.

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

// The one Amount column here is the entry's total debit leg(s). Signed
// `amount` (positive debit, negative credit) is `find_duplicate_groups`'s
// own shape — see `repository.lines_for_entries_signed`'s docstring.
function debitTotal(entry: DuplicateEntry): number {
  return entry.lines.filter((l) => Number(l.amount) > 0).reduce((sum, l) => sum + Number(l.amount), 0)
}

function findLeg(entry: DuplicateEntry, accountId: number, amount: string | number): DuplicateLine | undefined {
  return entry.lines.find((l) => l.account_id === accountId && Number(l.amount) === Number(amount))
}

// The "one has it, the other doesn't → use the one that does; both have
// it → use whichever is longer" rule, folded pairwise left-to-right
// across however many entries are being merged. Order doesn't matter
// for the outcome — "longer wins" and "non-blank wins over blank" are
// both associative/commutative — only the running "best so far" needs
// carrying between steps.
function autoAssignString(values: string[]): string {
  return values.reduce((best, v) => {
    const bestTrim = best.trim()
    const vTrim = v.trim()
    if (!bestTrim) return v
    if (!vTrim) return best
    return vTrim.length > bestTrim.length ? v : best
  })
}

// Same rule as autoAssignString, but on Payee — compared by name length
// (there's no other sense of "longer" for an id), with the id/name pair
// carried along together so the winning name maps back to the right id.
function autoAssignPayee(entries: DuplicateEntry[]): { payeeId: string; payeeName: string } {
  const winnerName = autoAssignString(entries.map((e) => e.payee_name || ''))
  const winner = entries.find((e) => (e.payee_name || '') === winnerName) ?? entries[0]
  return { payeeId: winner.payee_id != null ? String(winner.payee_id) : '', payeeName: winnerName }
}

// Applies autoAssignString per line, matching each of the first entry's
// legs to its counterpart on every other entry by (account, amount) —
// the same "same account+amount, so it's the same line" match
// `findLeg` exists for, never guessing across a different leg.
function autoAssignMemos(entries: DuplicateEntry[]): Record<number, string> {
  const [first, ...rest] = entries
  const memos: Record<number, string> = {}
  for (const line of first.lines) {
    const values = [line.memo || '', ...rest.map((e) => findLeg(e, line.account_id, line.amount)?.memo || '')]
    memos[line.id] = autoAssignString(values)
  }
  return memos
}

interface AutoFields {
  description: string
  reference: string
  payeeId: string
  tagsCsv: string
  memos: Record<number, string>
}

// The single field-resolution path every merge goes through, whether
// it's headed straight to the API (fields already agreed, or
// auto-assign is on) or just pre-filling the manual dialog for a person
// to review. When every entry already agrees on a field, folding it
// through autoAssignString/autoAssignMemos is a no-op — it returns that
// same shared value — so there's no separate "already equal" branch
// needed here at all; allFieldsMatch below is only about whether to
// *show* the result, never about how to compute it.
function computeAutoFields(entries: DuplicateEntry[]): AutoFields {
  const payee = autoAssignPayee(entries)
  const unionTags = new Set<string>()
  entries.forEach((e) => e.tags.forEach((t) => unionTags.add(t)))
  return {
    description: autoAssignString(entries.map((e) => e.description)),
    reference: autoAssignString(entries.map((e) => e.reference || '')),
    payeeId: payee.payeeId,
    tagsCsv: Array.from(unionTags).join(','),
    memos: autoAssignMemos(entries),
  }
}

// Whether every checked entry in a group already agrees on Description,
// Reference, Payee, and every line's Memo — the condition for skipping
// the merge-detail dialog outright, since there'd be nothing left for a
// person to decide between. Tags deliberately excluded — see this
// file's own top comment on why a tag-set union never needs asking.
function allFieldsMatch(entries: DuplicateEntry[]): boolean {
  const [first, ...rest] = entries
  if (rest.some((e) => e.description !== first.description)) return false
  if (rest.some((e) => (e.reference || '') !== (first.reference || ''))) return false
  if (rest.some((e) => e.payee_id !== first.payee_id)) return false
  for (const line of first.lines) {
    const val = line.memo || ''
    if (rest.some((e) => (findLeg(e, line.account_id, line.amount)?.memo || '') !== val)) return false
  }
  return true
}

// A small per-group tri-state "select all in this section" checkbox —
// same checked/indeterminate convention every other select-all in the
// app uses, just scoped to one group's own entries rather than the whole
// page. Its own tiny component (rather than inlined JSX) purely so the
// imperative `indeterminate` set (a DOM-only property, no React prop for
// it — see `useSelectMode.ts`'s own identical comment) has a natural
// effect to live in, keyed on this group's own counts.
//
// Sits to the left of the group's own date/account label with no
// visible words next to it (flagged after the first pass spelled out
// "select all in this section" beside every heading — too much text
// repeated once per group) — the checkbox alone reads clearly enough in
// context, same as the per-row checkboxes below it never carry a label
// either. `.sr-only` keeps a real accessible name for anyone not
// reading the visual layout.
function GroupSelectAll({ checkedCount, total, onToggle }: { checkedCount: number; total: number; onToggle: () => void }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.checked = checkedCount === total && total > 0
    el.indeterminate = checkedCount > 0 && checkedCount < total
  }, [checkedCount, total])
  return (
    <label className="checkline group-select-all select-only">
      <input ref={ref} type="checkbox" onChange={onToggle} />
      <span className="sr-only">Select all entries in this group</span>
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

interface MergeDetail {
  group: DuplicateGroup
  survivor: DuplicateEntry
  others: DuplicateEntry[]
}

export default function StagingDuplicatesPage() {
  const [result, setResult] = useState<DuplicatesResult | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  // When on, a group whose checked entries disagree on a field never
  // opens the manual dialog at all — autoAssignFields's guess is used
  // outright. Off by default: silently picking a value is a fine
  // default for the common "everything actually matches" case (handled
  // by allFieldsMatch regardless of this toggle), but a real
  // disagreement is exactly the case a person likely wants to see.
  const [autoAssign, setAutoAssign] = useState(false)

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
  const selectAllRef = useRef<HTMLInputElement>(null)
  const select = useSelectMode<string>(allEntryIds, selectAllRef)

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

  // Every group with 2+ entries checked right now — what Merge is about
  // to process, all of them in one click, not just the first.
  const mergeableGroups = useMemo(() => groups.filter((g) => checkedCountIn(g) >= 2), [groups, select.checkedIds])

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
  // A queue, not a single value: several groups in one Merge click can
  // each need a person's own field decision, and only one modal can be
  // on screen at a time. dialogQueue[0] is always "the one currently
  // shown"; saving or cancelling it just shifts the queue, which
  // re-primes the form for whatever's next (or closes the modal once
  // the queue's empty).
  const [dialogQueue, setDialogQueue] = useState<MergeDetail[]>([])
  const mergeDetail = dialogQueue[0] ?? null
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

  // Primes the form (and focuses/selects Description) every time the
  // dialog's own target changes — on first open, and again each time
  // saving or cancelling advances dialogQueue to its next entry. Always
  // seeded from computeAutoFields's own best guess (the field-agreement
  // case and the disagreement case both go through it — see this file's
  // own top comment) rather than the survivor's bare values, so the
  // pre-fill is never worse than what auto-assign would have picked
  // silently; a person is still free to overtype anything before saving.
  useEffect(() => {
    if (!mergeDetail) return
    const entries = [mergeDetail.survivor, ...mergeDetail.others]
    const auto = computeAutoFields(entries)
    setDescription(auto.description)
    setReference(auto.reference)
    setPayeeId(auto.payeeId)
    setTagsCsv(auto.tagsCsv)
    setMemos(auto.memos)
    setDialogError(null)
    descriptionRef.current?.focus()
    descriptionRef.current?.select()
  }, [mergeDetail])

  // Escape cancels, same as every other overlay in the app — not gated
  // on `saving` (a save is a single fast POST; there's no meaningful
  // window where a user would hit Escape mid-save and expect it to be
  // ignored, and the backdrop-click handler below already carries that
  // same guard for the slower, accidental-click case).
  useEffect(() => {
    if (!mergeDetail) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') cancelMergeDetail()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- cancelMergeDetail is a stable setState-updater closure, not a stale read
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

  // Skips the current entry in the queue without merging it — used by
  // Cancel, Escape, and the backdrop click. The rest of dialogQueue (any
  // other group still waiting on its own decision) is untouched.
  function cancelMergeDetail() {
    setDialogQueue((q) => q.slice(1))
  }

  // The one call to the merge endpoint every path below goes through —
  // the auto-resolved groups in handleMergeClick and the manual dialog's
  // own Save both end here. Returns the outcome rather than setting
  // flash/dialogError itself, since the two callers surface a failure
  // differently (a page-level flash for a silent auto-merge, an inline
  // message that keeps the dialog open for a manual one).
  async function performMerge(
    survivor: DuplicateEntry,
    others: DuplicateEntry[],
    descriptionVal: string,
    referenceVal: string,
    payeeIdVal: string,
    tagsCsvVal: string,
    lineMemos: Record<number, string>,
  ): Promise<{ ok: true; keptId: string } | { ok: false; error: string }> {
    const memosStr: Record<string, string> = {}
    for (const [lineId, val] of Object.entries(lineMemos)) memosStr[lineId] = val.trim()
    const { data, error: err } = await client.POST('/staging/duplicates/merge', {
      body: {
        keep_id: survivor.id,
        remove_ids: others.map((o) => o.id),
        description: descriptionVal.trim(),
        reference: referenceVal.trim() || null,
        payee_id: payeeIdVal ? Number(payeeIdVal) : null,
        tags: tagsCsvVal,
        line_memos: memosStr,
      },
    })
    if (err) return { ok: false, error: errorDetail(err, 'Could not merge these entries') }
    return { ok: true, keptId: (data as unknown as { kept_entry_id: string }).kept_entry_id }
  }

  // Checking 2+ entries within a group enables Merge. Clicking it now
  // walks every group that currently qualifies, not just the first:
  // for each, an unchecked sibling still triggers the three-way ask
  // exactly as before, but once a group's own checked set is settled,
  // it merges immediately (no dialog) whenever its fields already agree
  // or "automatically assign fields" is on — otherwise it's queued for
  // the one-at-a-time manual dialog below. `reload()` runs once at the
  // end for whatever merged automatically; the manual dialog's own Save
  // reloads again after each of its own merges, same as before.
  async function handleMergeClick() {
    if (mergeableGroups.length === 0) return

    const autoPlans: { survivor: DuplicateEntry; others: DuplicateEntry[]; fields: AutoFields }[] = []
    const manualPlans: MergeDetail[] = []

    for (const group of mergeableGroups) {
      let checkedIds = group.entries.filter((e) => select.checkedIds.has(e.id)).map((e) => e.id)
      const uncheckedCount = group.entries.length - checkedIds.length

      if (uncheckedCount > 0) {
        const noun = uncheckedCount === 1 ? 'entry' : 'entries'
        const verb = uncheckedCount === 1 ? 'is' : 'are'
        const choice = await askThreeWay(
          `“${group.label}” — another ${noun} matching the same accounts, amounts and date ${verb} not being included. Proceed with just the checked ones?`,
        )
        if (choice === 'cancel') continue
        if (choice === 'select') {
          group.entries.forEach((e) => {
            if (!select.checkedIds.has(e.id)) select.toggleChecked(e.id)
          })
          checkedIds = group.entries.map((e) => e.id)
        }
      }

      const entries = group.entries.filter((e) => checkedIds.includes(e.id))
      const survivor = entries[0]
      const others = entries.slice(1)

      if (allFieldsMatch(entries) || autoAssign) {
        autoPlans.push({ survivor, others, fields: computeAutoFields(entries) })
      } else {
        manualPlans.push({ group, survivor, others })
      }
    }

    let mergedCount = 0
    let firstError: string | null = null
    let lastKeptId = ''
    for (const plan of autoPlans) {
      const res = await performMerge(
        plan.survivor,
        plan.others,
        plan.fields.description,
        plan.fields.reference,
        plan.fields.payeeId,
        plan.fields.tagsCsv,
        plan.fields.memos,
      )
      if (res.ok) {
        mergedCount++
        lastKeptId = res.keptId
      } else if (!firstError) {
        firstError = res.error
      }
    }

    if (mergedCount > 0) await reload()

    if (mergedCount > 0) {
      const mergedMsg = mergedCount === 1 ? `Merged into #${lastKeptId}` : `Merged ${mergedCount} duplicate sets`
      const queuedMsg =
        manualPlans.length > 0
          ? ` — ${manualPlans.length} more need${manualPlans.length === 1 ? 's' : ''} your input below.`
          : ''
      setFlash({ ok: mergedMsg + queuedMsg })
    } else if (firstError) {
      setFlash({ err: firstError })
    }

    if (manualPlans.length > 0) setDialogQueue(manualPlans)
  }

  async function saveMergeDetail() {
    if (!mergeDetail) return
    setSaving(true)
    setDialogError(null)
    const res = await performMerge(mergeDetail.survivor, mergeDetail.others, description, reference, payeeId, tagsCsv, memos)
    setSaving(false)
    if (!res.ok) {
      setDialogError(res.error)
      return
    }
    setDialogQueue((q) => q.slice(1))
    setFlash({ ok: `Merged into #${res.keptId}` })
    // Select mode stays on (unlike Tags/Payees' own Merge, which always
    // exits it) — checking several duplicate sets and clicking Merge
    // used to only ever process the first one, since exiting select mode
    // wiped every other group's checked entries along with it. `reload()`
    // recomputes `groups`; useSelectMode's own effect prunes the merged/
    // removed entries out of checkedIds once it reflects the merge.
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
        <label className="checkline select-only">
          <input ref={selectAllRef} type="checkbox" onChange={select.toggleSelectAll} />
          select all
        </label>
        <label className="checkline select-only" title="When entries in a group disagree on a field, pick a value automatically instead of asking">
          <input type="checkbox" checked={autoAssign} onChange={(e) => setAutoAssign(e.target.checked)} />
          automatically assign fields
        </label>
        <button type="button" disabled={mergeableGroups.length === 0} onClick={handleMergeClick}>
          {mergeableGroups.length > 1 ? `Merge (${mergeableGroups.length})` : 'Merge'}
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
              <GroupSelectAll
                checkedCount={checkedCountIn(group)}
                total={group.entries.length}
                onToggle={() => toggleGroupAll(group)}
              />
              {group.label}
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
                    <td className="num money">{formatMoneyOrDash(debitTotal(e))}</td>
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
              if (e.target === e.currentTarget && !saving) cancelMergeDetail()
            }}
          >
            <div className="confirm-modal" role="dialog" aria-label="Merge duplicate entries">
              <h3>
                Merge {mergeDetail.others.length + 1} entries
                {dialogQueue.length > 1 ? ` (${dialogQueue.length} groups left)` : ''}
              </h3>

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
                <button type="button" className="quiet" onClick={cancelMergeDetail} disabled={saving}>
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
