import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import type { Payee } from '../api/usePayees'
import { usePayees } from '../api/usePayees'
import { useScenarios } from '../api/useScenarios'
import { useTags } from '../api/useTags'
import { altLabel } from '../format/shortcut'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import { useConfirm } from '../widgets/confirmContext'
import { usePostableAccounts } from '../widgets/usePostableAccounts'
import TagInput from '../widgets/TagInput'
import EntryGrid from '../journal/EntryGrid'
import { ensureTrailingBlank, isLineUsed, makeBlankLine, type GridLine } from '../journal/gridLines'

// Ported from app/templates/entry_templates.html (Phase 4.2) — the same
// `table.ledger.entry-grid` + balance-bar shape `ScheduledPage.tsx`'s
// own Phase 4.2 write-up already explains sharing one `app.js` with the
// Journal's New entry panel over. Reuses `EntryGrid.tsx`/`gridLines.ts`
// unchanged, same as that page.
//
// Simpler than both `NewEntryPanel.tsx` and `ScheduledPage.tsx` in one
// real way: entry templates aren't scenario-bound at all (`app/main.py`'s
// own comment on `templates_full`, ported verbatim into `modules/
// scheduling/repository.py`) — no Scenario field, and the account picker
// uses `usePostableAccounts()`'s own `forPickers` (the union across every
// scenario), exactly the case that field's own Phase 3.4 docstring
// names as its reason for existing ("entry_templates.html isn't
// scenario-bound"). Balance is still unconditionally required
// (`modules/scheduling/service.py::create_template`'s own `total != 0`
// check, identical to `create_schedule`'s), and the row of buttons below
// is Save/Add line/Distribute with no Clear, same as Scheduled.
//
// Delete (not archive — `entry_templates` carries no `is_active` column
// at all) is the one row action, confirmed the same way `AccountLevelsPage
// .tsx`'s own Delete already is.
interface TemplateLineRow {
  code: string
  debit: string | null
  credit: string | null
  memo: string | null
}

interface TemplateRow {
  id: number
  name: string
  description: string
  reference: string | null
  payee_id: number | null
  payee_name: string | null
  lines: TemplateLineRow[]
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

export default function EntryTemplatesPage() {
  const [templates, setTemplates] = useState<TemplateRow[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const confirm = useConfirm()

  const scenarios = useScenarios()
  const postableAccounts = usePostableAccounts(scenarios)
  const payees = usePayees()
  const tagOptions = useTags()
  const allTagNames = (tagOptions ?? []).map((t) => t.name)

  const [name, setName] = useState('')
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
    const { data } = await client.GET('/templates')
    if (data) setTemplates(data as unknown as TemplateRow[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/templates').then(({ data }) => {
      if (!cancelled && data) setTemplates(data as unknown as TemplateRow[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  const accountOptions: ComboboxOption[] = useMemo(
    () => (postableAccounts?.forPickers ?? []).map((a) => ({ value: a.code, label: `${a.code} · ${a.name}` })),
    [postableAccounts],
  )

  const payeeOptions: ComboboxOption[] = useMemo(
    () => [
      { value: '', label: 'None' },
      ...(payees ?? []).map((p) => ({ value: String(p.id), label: p.name })),
      ...createdPayees.map((p) => ({ value: String(p.id), label: p.name })),
    ],
    [payees, createdPayees],
  )

  async function createPayee(payeeName: string): Promise<ComboboxOption | null> {
    const { data, error: err } = await client.POST('/payees/quick-create', { body: { name: payeeName } })
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
    const { error: err } = await client.POST('/templates', {
      body: {
        name,
        description,
        reference: reference || undefined,
        payee_id: payeeId ? Number(payeeId) : undefined,
        tags: tagsCsv,
        lines: used.map((l) => ({ account: l.account, debit: l.debit, credit: l.credit, memo: l.memo || undefined })),
      },
    })
    setSaving(false)
    if (err) {
      setError(errorDetail(err, 'Could not save template'))
      return
    }
    setFlash({ ok: `Template “${name}” saved` })
    setName('')
    setDescription('')
    setReference('')
    setPayeeId('')
    setTagsCsv('')
    setLines([makeBlankLine(), makeBlankLine()])
    await reload()
  }

  async function deleteTemplate(t: TemplateRow) {
    const ok = await confirm(`Delete template ${t.name}?`, { okLabel: 'Delete', danger: true })
    if (!ok) return
    const { error: err } = await client.POST('/templates/{template_id}/delete', {
      params: { path: { template_id: t.id } },
    })
    if (err) {
      setFlash({ err: errorDetail(err, 'Could not delete template') })
      return
    }
    setFlash({ ok: `“${t.name}” deleted` })
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

  if (templates === null || postableAccounts === null || payees === null) {
    return <p>Loading…</p>
  }

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#templates" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <table className="ledger">
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            <th>Payee</th>
            <th>Lines</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {templates.length === 0 && (
            <tr>
              <td colSpan={5} className="dim">
                No templates yet.
              </td>
            </tr>
          )}
          {templates.map((t) => (
            <tr key={t.id}>
              <td>{t.name}</td>
              <td className="dim">{t.description}</td>
              <td className="dim">{t.payee_name || '—'}</td>
              <td className="dim">{t.lines.length}</td>
              <td>
                <button type="button" className="quiet" onClick={() => deleteTemplate(t)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <h2>New template</h2>
        {error && <div className="flash flash-err">{error}</div>}
        <form onSubmit={submit} ref={formRef}>
          <div className="bar">
            <label className="field">
              Template name
              <input
                type="text"
                required
                placeholder="e.g. Monthly rent"
                value={name}
                onChange={(e) => setName(e.target.value)}
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
              {balanced ? '' : 'Debits and credits must be equal before this template can be saved.'}
            </span>
          </div>

          <p style={{ marginTop: '1rem' }}>
            <button type="submit" disabled={saveDisabled}>
              Save template ({altLabel('S')})
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
