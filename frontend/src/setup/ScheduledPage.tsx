import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import client from '../api/client'
import type { Payee } from '../api/usePayees'
import { usePayees } from '../api/usePayees'
import { useScenarios } from '../api/useScenarios'
import { useTags } from '../api/useTags'
import { formatDate } from '../format/date'
import { altLabel } from '../format/shortcut'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import { usePostableAccounts } from '../widgets/usePostableAccounts'
import TagInput from '../widgets/TagInput'
import EntryGrid from '../journal/EntryGrid'
import { ensureTrailingBlank, isLineUsed, makeBlankLine, type GridLine } from '../journal/gridLines'

// Ported from app/templates/scheduled.html (Phase 4.2) — the New
// schedule form is the same `table.ledger.entry-grid` + balance-bar
// shape as the Journal's own New entry panel (Phase 3.4), sharing one
// `app.js` between both legacy pages, so this reuses `EntryGrid.tsx`/
// `gridLines.ts` unchanged and mirrors `NewEntryPanel.tsx`'s own
// state/handlers rather than reinventing them. Three real differences
// from that panel, not a shared abstraction of the two:
//
// 1. A permanent `<div class="panel">`, not a collapsible `<details>` —
//    scheduled.html never wraps its form in one (same "add UI is a
//    permanent panel" shape ScenariosPage.tsx's own Phase 4.2 write-up
//    already ported for a different screen) — so no Alt+E open/close
//    shortcut, no `defaultOpen`/`onPosted` handshake with a parent list.
// 2. Repeats-every/unit/Next-on fields replace a single Date field, and
//    `target_scenario_id` always requires balance — `modules/scheduling/
//    service.py::create_schedule`'s own `total != 0` check is
//    unconditional, unlike `modules/entries/service.py`'s scenario-
//    dependent `enforce_balance`. The "(single-sided OK)" suffix on a
//    non-enforcing scenario's own label is kept (matches legacy's
//    `data-enforce` text) since it still describes a real property of
//    that scenario — just not a rule *this* form's Save button honors.
// 3. No Clear button, no Alt+C — scheduled.html's own button row only
//    ever had Save/Add line/Distribute.
//
// The `pending_count` Staging banner (scheduled.html's own
// `flash-warn`) is deliberately not ported here — Staging itself
// (Phase 4.3) doesn't have a JSON shape this page has ever read yet,
// and `/staging`'s bare route isn't a client route either. Revisit once
// Phase 4.3 gives this page something real to read and link to, same
// "don't reach into a screen that doesn't exist yet" reasoning
// `TagsPage.tsx`'s own Phase 3.2 write-up already applied to Journal.
type IntervalUnit = 'day' | 'week' | 'month'
const INTERVAL_UNITS: IntervalUnit[] = ['day', 'week', 'month']

interface ScheduleRow {
  id: number
  description: string
  reference: string | null
  payee_name: string | null
  scenario_code: string
  interval_unit: IntervalUnit
  interval_count: number
  next_date: string
  is_active: boolean
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

const today = new Date().toISOString().slice(0, 10)

export default function ScheduledPage() {
  const [schedules, setSchedules] = useState<ScheduleRow[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  const scenarios = useScenarios()
  const postableAccounts = usePostableAccounts(scenarios)
  const payees = usePayees()
  const tagOptions = useTags()
  const allTagNames = (tagOptions ?? []).map((t) => t.name)

  const eligibleScenarios = useMemo(
    () => (scenarios ?? []).filter((s) => !s.is_locked && !s.income_statement_only && !s.is_staging),
    [scenarios],
  )
  const firstScenarioId = eligibleScenarios[0]?.id ?? 0

  const [intervalCount, setIntervalCount] = useState('1')
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>('month')
  const [nextDate, setNextDate] = useState(today)
  // `null` until the user actually picks one — `scenarios` loads
  // asynchronously (this component is mounted, and its hooks run,
  // before the loading guard below can ever return early), so a plain
  // `useState(firstScenarioId)` would permanently freeze on whatever
  // `firstScenarioId` happened to be on the very first render (0,
  // before data arrives). Derived below instead of synced via an
  // effect — a `setState`-in-`useEffect` `oxlint` flags as the
  // "cascading renders" smell its own message describes; deriving
  // during render is the fix it suggests.
  const [explicitScenarioId, setExplicitScenarioId] = useState<number | null>(null)
  const scenarioId = explicitScenarioId ?? firstScenarioId
  const [description, setDescription] = useState('')
  const [reference, setReference] = useState('')
  const [payeeId, setPayeeId] = useState('')
  const [tagsCsv, setTagsCsv] = useState('')
  const [lines, setLines] = useState<GridLine[]>(() => [makeBlankLine(), makeBlankLine()])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [createdPayees, setCreatedPayees] = useState<Payee[]>([])

  const formRef = useRef<HTMLFormElement>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const lastFocusedKey = useRef<string | null>(null)

  const reload = useCallback(async () => {
    const { data } = await client.GET('/scheduled')
    if (data) setSchedules(data as unknown as ScheduleRow[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/scheduled').then(({ data }) => {
      if (!cancelled && data) setSchedules(data as unknown as ScheduleRow[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  const accountOptions: ComboboxOption[] = useMemo(() => {
    const list = postableAccounts?.byScenario.get(scenarioId) ?? []
    return list.map((a) => ({ value: a.code, label: `${a.code} · ${a.name}` }))
  }, [postableAccounts, scenarioId])

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
  const saveDisabled = saving || !balanced

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    const used = lines.filter(isLineUsed)
    const { error: err } = await client.POST('/scheduled', {
      body: {
        description,
        reference: reference || undefined,
        payee_id: payeeId ? Number(payeeId) : undefined,
        target_scenario_id: scenarioId,
        interval_unit: intervalUnit,
        interval_count: Number(intervalCount),
        next_date: nextDate || undefined,
        tags: tagsCsv,
        lines: used.map((l) => ({ account: l.account, debit: l.debit, credit: l.credit, memo: l.memo || undefined })),
      },
    })
    setSaving(false)
    if (err) {
      setError(errorDetail(err, 'Could not save schedule'))
      return
    }
    setDescription('')
    setReference('')
    setPayeeId('')
    setTagsCsv('')
    setLines([makeBlankLine(), makeBlankLine()])
    setFlash({ ok: `Schedule “${description}” saved` })
    await reload()
  }

  async function toggleActive(s: ScheduleRow) {
    const { error: err } = await client.POST('/scheduled/{scheduled_id}/toggle-active', {
      params: { path: { scheduled_id: s.id } },
    })
    if (err) {
      setFlash({ err: errorDetail(err, 'Could not update schedule') })
      return
    }
    setFlash({ ok: s.is_active ? `“${s.description}” archived` : `“${s.description}” unarchived` })
    await reload()
  }

  // e.code, not e.key — same macOS-Option-remap reasoning
  // NewEntryPanel.tsx's own identical handler already documents.
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

  if (schedules === null || scenarios === null || postableAccounts === null || payees === null) {
    return <p>Loading…</p>
  }

  return (
    <>
      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <table className="ledger">
        <thead>
          <tr>
            <th>Description</th>
            <th>Payee</th>
            <th>Target scenario</th>
            <th>Repeats</th>
            <th>Next</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {schedules.length === 0 && (
            <tr>
              <td colSpan={7} className="dim">
                No scheduled entries yet.
              </td>
            </tr>
          )}
          {schedules.map((s) => (
            <tr key={s.id}>
              <td>
                {s.description}
                {s.reference && <span className="dim small"> [{s.reference}]</span>}
              </td>
              <td className="dim">{s.payee_name || '—'}</td>
              <td className="mono dim">{s.scenario_code}</td>
              <td>
                every {s.interval_count} {s.interval_unit}
                {s.interval_count !== 1 ? 's' : ''}
              </td>
              <td className="mono">{formatDate(s.next_date)}</td>
              <td className="dim">{s.is_active ? 'active' : 'archived'}</td>
              <td>
                <button type="button" className="quiet" onClick={() => toggleActive(s)}>
                  {s.is_active ? 'Archive' : 'Unarchive'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <h2>New schedule</h2>
        {error && <div className="flash flash-err">{error}</div>}
        <form onSubmit={submit} ref={formRef}>
          <div className="bar">
            <label className="field" style={{ maxWidth: '6rem' }}>
              Repeats every
              <input
                type="number"
                min={1}
                value={intervalCount}
                onChange={(e) => setIntervalCount(e.target.value)}
              />
            </label>
            <label className="field" style={{ maxWidth: '9rem' }}>
              &nbsp;
              <select value={intervalUnit} onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}>
                {INTERVAL_UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}(s)
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Next on
              <DatePicker value={nextDate} onChange={setNextDate} />
            </label>
            <label className="field">
              Target scenario
              <Combobox
                options={eligibleScenarios.map((s) => ({
                  value: String(s.id),
                  label: `${s.code} — ${s.name}${s.enforce_balance ? '' : ' (single-sided OK)'}`,
                }))}
                value={String(scenarioId)}
                onChange={(v) => setExplicitScenarioId(Number(v))}
              />
            </label>
            <label className="field" style={{ flex: 1, minWidth: '16rem' }}>
              Description
              <input
                type="text"
                required
                placeholder="e.g. Rent"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="field">
              Reference
              <input
                type="text"
                placeholder="Optional"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
            </label>
            <label className="field">
              Payee
              <Combobox options={payeeOptions} value={payeeId} onChange={setPayeeId} onCreate={createPayee} />
            </label>
            <label className="field" style={{ flex: 1, minWidth: '14rem' }}>
              Tags
              <TagInput value={tagsCsv} onChange={setTagsCsv} suggestions={allTagNames} placeholder="Add a tag…" />
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
              <span className="lbl">Debits</span> {totals.deb.toFixed(2)}
            </span>
            <span>
              <span className="lbl">Credits</span> {totals.cre.toFixed(2)}
            </span>
            <span>
              <span className="lbl">Difference</span>{' '}
              <span className="diff">{Math.abs(totals.diff).toFixed(2)}</span>
            </span>
            <span className="dim small">
              {balanced ? '' : 'Debits and credits must be equal before this schedule can be saved.'}
            </span>
          </div>

          <p style={{ marginTop: '1rem' }}>
            <button type="submit" disabled={saveDisabled}>
              Save schedule ({altLabel('S')})
            </button>{' '}
            <button type="button" className="quiet" onClick={addRow}>
              Add line ({altLabel('N')})
            </button>{' '}
            <button
              type="button"
              className="quiet"
              title="Fill the current line with whatever balances the entry"
              onClick={distribute}
            >
              Distribute ({altLabel('D')})
            </button>
          </p>
        </form>
      </div>
    </>
  )
}
