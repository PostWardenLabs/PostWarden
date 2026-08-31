import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import client from '../api/client'
import type { Payee } from '../api/usePayees'
import type { Scenario } from '../api/useScenarios'
import { formatMoney, isZeroAmount } from '../format/money'
import { altLabel } from '../format/shortcut'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import type { PostableAccount } from '../widgets/usePostableAccounts'
import TagInput from '../widgets/TagInput'
import EntryGrid from '../journal/EntryGrid'
import { ensureTrailingBlank, isLineUsed, makeBlankLine, type GridLine } from '../journal/gridLines'

interface StagingEditPanelProps {
  entryId: string
  scenarios: Scenario[]
  postableByScenario: Map<number, PostableAccount[]>
  payees: Payee[]
  allTags: string[]
  onSaved: () => void
  onCancel: () => void
}

interface EditData {
  entry: { id: string; entry_date: string; description: string; reference: string; payee_id: number | null }
  lines: { id: number; debit: string; credit: string; memo: string | null; account_code: string }[]
  tags: string[]
  target_scenario_id: number
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// Staging's own "Edit" — relocates this in place of an entry's read-only
// row rather than navigating to a separate page (`StagingPage.tsx` renders
// this instead of that row once its own "Edit" button is clicked). Reuses
// `EntryGrid.tsx`/`gridLines.ts`, the same two files
// `NewEntryPanel.tsx`/`ScheduledPage.tsx`/`EntryTemplatesPage.tsx` already
// share — but mirrors `NewEntryPanel.tsx`'s own state/handlers rather than
// factoring a shared hook out of the two: real, small differences, not
// worth a shared abstraction. Differences from `NewEntryPanel.tsx`:
//
// 1. No scenario picker — a staged entry's target scenario is fixed by
//    whatever produced it (`GET /staging/{id}/edit`'s own `target_scenario_
//    id`), not chosen here; the account picker is filtered against it
//    directly instead of reacting to a `<select>` change.
// 2. Loads existing data (`GET /staging/{id}/edit`) instead of starting
//    blank — `journal_lines`' own debit/credit columns are `NUMERIC NOT
//    NULL DEFAULT 0`, so the unused side of each line always arrives as
//    `"0.00"`, not `null`/blank the way `entry_templates` lines store it;
//    `isZeroAmount` is what tells "really zero" apart from "a real 1-cent
//    leg" before blanking it back out for the input, same test
//    `JournalPage.tsx`'s own read-only cells already use for the same
//    reason.
// 3. No template loader, no Clear button, no Alt+E — this panel is always
//    already open by the time it mounts (`StagingPage.tsx` only renders it
//    once "Edit" is clicked), and "start over" here means Cancel, not a
//    blank form.
export default function StagingEditPanel({
  entryId,
  scenarios,
  postableByScenario,
  payees,
  allTags,
  onSaved,
  onCancel,
}: StagingEditPanelProps) {
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [targetScenarioId, setTargetScenarioId] = useState<number | null>(null)
  const [date, setDate] = useState('')
  const [description, setDescription] = useState('')
  const [reference, setReference] = useState('')
  const [payeeId, setPayeeId] = useState('')
  const [tagsCsv, setTagsCsv] = useState('')
  const [lines, setLines] = useState<GridLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [createdPayees, setCreatedPayees] = useState<Payee[]>([])

  const formRef = useRef<HTMLFormElement>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const lastFocusedKey = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/staging/{entry_id}/edit', { params: { path: { entry_id: entryId } } }).then(({ data, error: err }) => {
      if (cancelled) return
      if (err || !data) {
        setLoadError(errorDetail(err, 'Could not load this entry — it may have already been approved or rejected.'))
        return
      }
      const body = data as unknown as EditData
      setDate(body.entry.entry_date)
      setDescription(body.entry.description)
      setReference(body.entry.reference || '')
      setPayeeId(body.entry.payee_id != null ? String(body.entry.payee_id) : '')
      setTagsCsv(body.tags.join(','))
      setTargetScenarioId(body.target_scenario_id)
      setLines(
        ensureTrailingBlank(
          body.lines.map((l) => ({
            ...makeBlankLine(),
            account: l.account_code,
            debit: isZeroAmount(l.debit) ? '' : l.debit,
            credit: isZeroAmount(l.credit) ? '' : l.credit,
            memo: l.memo || '',
          })),
          null,
        ),
      )
      setLoaded(true)
    })
    return () => {
      cancelled = true
    }
  }, [entryId])

  const accountOptions: ComboboxOption[] = useMemo(() => {
    const list = targetScenarioId != null ? (postableByScenario.get(targetScenarioId) ?? []) : []
    return list.map((a) => ({ value: a.code, label: `${a.code} · ${a.name}` }))
  }, [postableByScenario, targetScenarioId])

  const payeeOptions: ComboboxOption[] = useMemo(
    () => [
      { value: '', label: 'None' },
      ...payees.map((p) => ({ value: String(p.id), label: p.name })),
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

  function updateLine(key: string, field: 'account' | 'debit' | 'credit' | 'memo', value: string) {
    setLines((ls) => {
      const next = ls.map((l) => {
        if (l.key !== key) return l
        const patch: Partial<GridLine> = { [field]: value }
        if (field === 'debit' && value.trim() !== '') patch.credit = ''
        if (field === 'credit' && value.trim() !== '') patch.debit = ''
        return { ...l, ...patch }
      })
      return ensureTrailingBlank(next, lastFocusedKey.current)
    })
  }

  function addRow() {
    setLines((ls) => [...ls, makeBlankLine()])
  }

  function distribute() {
    setLines((ls) => {
      let rows = ls
      let targetKey =
        lastFocusedKey.current && rows.some((l) => l.key === lastFocusedKey.current)
          ? lastFocusedKey.current
          : rows[rows.length - 1]?.key
      if (!targetKey) return rows
      if (targetKey === rows[0]?.key) {
        if (rows.length < 2) rows = [...rows, makeBlankLine()]
        targetKey = rows[1].key
      }
      let deb = 0
      let cre = 0
      for (const r of rows) {
        if (r.key === targetKey) continue
        deb += parseFloat(r.debit) || 0
        cre += parseFloat(r.credit) || 0
      }
      const diff = Math.round((deb - cre) * 100) / 100
      const next = rows.map((r) =>
        r.key === targetKey
          ? { ...r, credit: diff > 0 ? diff.toFixed(2) : '', debit: diff < 0 ? (-diff).toFixed(2) : '' }
          : r,
      )
      return ensureTrailingBlank(next, lastFocusedKey.current)
    })
  }

  const totals = useMemo(() => {
    let deb = 0
    let cre = 0
    for (const l of lines) {
      deb += parseFloat(l.debit) || 0
      cre += parseFloat(l.credit) || 0
    }
    return { deb, cre, diff: Math.round((deb - cre) * 100) / 100 }
  }, [lines])
  const balanced = totals.diff === 0 && (totals.deb > 0 || totals.cre > 0)
  const scenarioObj = targetScenarioId != null ? scenarios.find((s) => s.id === targetScenarioId) : undefined
  const enforcing = scenarioObj ? scenarioObj.enforce_balance : true
  const saveDisabled = saving || (enforcing ? !balanced : totals.deb === 0 && totals.cre === 0)
  const balanceMsg = balanced
    ? 'Balanced — ready to save.'
    : enforcing
      ? 'Debits and credits must be equal before this entry can be saved.'
      : 'This scenario accepts single-sided entries; balance is optional.'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    const used = lines.filter(isLineUsed)
    const { error: err } = await client.POST('/staging/{entry_id}/edit', {
      params: { path: { entry_id: entryId } },
      body: {
        entry_date: date || undefined,
        description,
        reference: reference || undefined,
        payee_id: payeeId ? Number(payeeId) : undefined,
        tags: tagsCsv,
        lines: used.map((l) => ({ account: l.account, debit: l.debit, credit: l.credit, memo: l.memo || undefined })),
      },
    })
    setSaving(false)
    if (err) {
      setError(errorDetail(err, 'Could not save changes'))
      return
    }
    onSaved()
  }

  // e.code, not e.key — same macOS-Option-remap reasoning
  // NewEntryPanel.tsx's/ScheduledPage.tsx's own identical handlers already
  // document.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!e.altKey) return
      if (e.code === 'KeyN') {
        e.preventDefault()
        addRow()
      } else if (e.code === 'KeyD') {
        e.preventDefault()
        distribute()
      } else if (e.code === 'KeyS') {
        e.preventDefault()
        formRef.current?.requestSubmit()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  if (!loaded) {
    return loadError ? (
      <>
        <div className="flash flash-err">{loadError}</div>
        <button type="button" className="quiet" onClick={onCancel}>
          Close
        </button>
      </>
    ) : (
      <p className="dim">Loading…</p>
    )
  }

  return (
    <>
      {error && <div className="flash flash-err">{error}</div>}
      <form onSubmit={submit} ref={formRef}>
        <div className="bar">
          <label className="field">
            Date
            <DatePicker value={date} onChange={setDate} />
          </label>
          <label className="field" style={{ flex: 1, minWidth: '16rem' }}>
            Description
            <input type="text" required value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="field">
            Reference
            <input type="text" placeholder="Optional" value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          <label className="field">
            Payee
            <Combobox options={payeeOptions} value={payeeId} onChange={setPayeeId} onCreate={createPayee} />
          </label>
          <label className="field" style={{ flex: 1, minWidth: '14rem' }}>
            Tags
            <TagInput value={tagsCsv} onChange={setTagsCsv} suggestions={allTags} placeholder="Add a tag…" />
          </label>
        </div>

        <EntryGrid
          lines={lines}
          accounts={accountOptions}
          updateLine={updateLine}
          tableRef={tableRef}
          onFocusRow={(key) => {
            lastFocusedKey.current = key
          }}
        />

        <div className={'balance-bar' + (balanced ? ' balanced' : ' unbalanced')}>
          <span>
            <span className="lbl">Debits</span> {formatMoney(totals.deb)}
          </span>
          <span>
            <span className="lbl">Credits</span> {formatMoney(totals.cre)}
          </span>
          <span>
            <span className="lbl">Difference</span> <span className="diff">{formatMoney(Math.abs(totals.diff))}</span>
          </span>
          <span className="dim small">{balanceMsg}</span>
        </div>

        <p className="bar" style={{ marginTop: '1rem', justifyContent: 'space-between' }}>
          <span className="bar" style={{ gap: '0.7rem', marginBottom: 0 }}>
            <button type="submit" disabled={saveDisabled}>
              Save changes ({altLabel('S')})
            </button>
            <button type="button" className="quiet" onClick={addRow}>
              Add line ({altLabel('N')})
            </button>
            <button
              type="button"
              className="quiet"
              title="Fill the current line with whatever balances the entry"
              onClick={distribute}
            >
              Distribute ({altLabel('D')})
            </button>
          </span>
          <button type="button" className="quiet" onClick={onCancel}>
            Cancel
          </button>
        </p>
      </form>
    </>
  )
}
