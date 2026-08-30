import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import client from '../api/client'
import type { Payee } from '../api/usePayees'
import type { Scenario } from '../api/useScenarios'
import type { Template } from '../api/useTemplates'
import { formatMoney } from '../format/money'
import { altLabel } from '../format/shortcut'
import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import DatePicker from '../widgets/DatePicker'
import type { PostableAccount } from '../widgets/usePostableAccounts'
import TagInput from '../widgets/TagInput'
import EntryGrid from './EntryGrid'
import { ensureTrailingBlank, isLineUsed, makeBlankLine, type GridLine } from './gridLines'

interface NewEntryPanelProps {
  scenarios: Scenario[]
  postableByScenario: Map<number, PostableAccount[]>
  payees: Payee[]
  templates: Template[]
  allTags: string[]
  defaultOpen: boolean
  onPosted: (entryId: string) => void
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

const today = new Date().toISOString().slice(0, 10)

// Ported from entries.html's `details#new-entry-panel` + app.js (Phase
// 3.4) — the New entry form. `EntryGrid.tsx` owns the line table itself;
// this owns the rest: header fields, the balance bar, Post/Add line/
// Distribute/Clear, template loading, and the fetch-based submit that
// shows a rejected entry's error inline instead of losing what was
// typed (app.js's own reason for `fetch` over a plain form POST).
//
// `<details>` stays genuinely uncontrolled (a plain ref and direct
// `.open =` assignment, no `open` prop at all) rather than React state —
// the same technique `TagsPage.tsx`'s own "+ Add tag" panel already used
// (Phase 3.2), for the same reason: nothing here needs to *react* to
// open/closed, only toggle it, and a controlled `open` would fight the
// very first native `<summary>` click by reasserting itself next render.
export default function NewEntryPanel({
  scenarios,
  postableByScenario,
  payees,
  templates,
  allTags,
  defaultOpen,
  onPosted,
}: NewEntryPanelProps) {
  const eligibleScenarios = useMemo(
    () => scenarios.filter((s) => !s.is_locked && !s.income_statement_only && !s.is_staging),
    [scenarios],
  )
  const firstScenarioId = eligibleScenarios[0]?.id ?? 0

  const [date, setDate] = useState(today)
  const [scenarioId, setScenarioId] = useState(firstScenarioId)
  const [description, setDescription] = useState('')
  const [reference, setReference] = useState('')
  const [payeeId, setPayeeId] = useState('')
  const [tagsCsv, setTagsCsv] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [lines, setLines] = useState<GridLine[]>(() => [makeBlankLine(), makeBlankLine()])
  const [error, setError] = useState<string | null>(null)
  const [posting, setPosting] = useState(false)
  // Payees created inline mid-form via the picker's own "+ Create" row
  // (legacy: entry_new.html's `data-create-url="/payees/quick-create"`) —
  // kept separate from the `payees` prop rather than pushed back up into
  // it, since `usePayees()` is a one-shot fetch-on-mount hook with no
  // setter; merged into the options list below so a payee created this
  // way is immediately selectable without a re-fetch.
  const [createdPayees, setCreatedPayees] = useState<Payee[]>([])

  const detailsRef = useRef<HTMLDetailsElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const descriptionRef = useRef<HTMLInputElement>(null)
  // Distribute needs "whichever row the grid's focus was last in" — by
  // the time its own click handler runs, focus has already moved to the
  // Distribute button itself (same "focus moves to a clicked button
  // before its click event fires" gap app.js's own comment describes),
  // so this tracks it continuously via EntryGrid's onFocus instead of
  // reading document.activeElement at click time. A ref, not state:
  // Distribute reads it imperatively and nothing should re-render when
  // focus merely moves between cells.
  const lastFocusedKey = useRef<string | null>(null)
  // Staged by addRow()/distribute()/Alt+E, consumed by the effect below
  // once the DOM the target field lives in has actually committed —
  // the same "stage in a ref, focus in an effect after commit" pattern
  // DatePicker.tsx's own arrow-key navigation already established,
  // needed here for the identical reason: React can't synchronously
  // query a node that doesn't exist until after this render lands.
  const pendingFocus = useRef<{ key: string; field: 'account' | 'debit' | 'credit' } | null>(null)

  useEffect(() => {
    if (!pendingFocus.current) return
    const { key, field } = pendingFocus.current
    pendingFocus.current = null
    const el = tableRef.current?.querySelector(
      `tr[data-row-key="${key}"] td[data-col="${field}"] .combobox-input, tr[data-row-key="${key}"] td[data-col="${field}"] input`,
    ) as HTMLElement | null
    el?.focus()
  }, [lines])

  // No `open`/`defaultOpen` prop — React's `<details>` typings don't
  // carry a `defaultOpen`, and a controlled `open` would fight every
  // later native/ref-based toggle (the summary click, Alt+E) the moment
  // a re-render reasserted it. Same plain-ref, no-prop shape
  // `TagsPage.tsx`'s own "+ Add tag" panel already uses; this one just
  // needs an extra one-time push open on mount when `?new=1` asked for
  // it, matching legacy's own `{{ 'open' if request.query_params.get
  // ('new') }}`.
  useEffect(() => {
    if (defaultOpen && detailsRef.current) detailsRef.current.open = true
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only, defaultOpen is a prop snapshot from the URL at load
  }, [])

  const accountOptions: ComboboxOption[] = useMemo(() => {
    const list = postableByScenario.get(scenarioId) ?? []
    return list.map((a) => ({ value: a.code, label: `${a.code} · ${a.name}` }))
  }, [postableByScenario, scenarioId])

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

  // Re-filters every line's account picker to whatever the newly
  // selected scenario can actually post to — ported from app.js's
  // `refreshAccountsForScenario`. Skipped on the very first render
  // (nothing to clear yet) via the ref below, same "only on a real
  // change" guard `TrialBalancePage.tsx`'s own effects don't need but
  // this one does, since mount and "scenario changed to the same
  // default" are otherwise indistinguishable from a bare `[scenarioId]`
  // dependency.
  const mounted = useRef(false)
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true
      return
    }
    const codes = new Set(accountOptions.map((o) => o.value))
    setLines((ls) => ls.map((l) => (codes.has(l.account) ? l : { ...l, account: '' })))
  }, [scenarioId, accountOptions])

  function updateLine(key: string, field: 'account' | 'debit' | 'credit' | 'memo', value: string) {
    setLines((ls) => {
      const next = ls.map((l) => {
        if (l.key !== key) return l
        const patch: Partial<GridLine> = { [field]: value }
        // One side per line, exactly like the paper form — entering a
        // debit clears that line's own credit, and vice versa.
        if (field === 'debit' && value.trim() !== '') patch.credit = ''
        if (field === 'credit' && value.trim() !== '') patch.debit = ''
        return { ...l, ...patch }
      })
      return ensureTrailingBlank(next, lastFocusedKey.current)
    })
  }

  function addRow() {
    const line = makeBlankLine()
    setLines((ls) => [...ls, line])
    pendingFocus.current = { key: line.key, field: 'account' }
  }

  // Ported from app.js's own Distribute — see its file comment for the
  // full reasoning on the first-row special case and why this targets
  // the *existing* next row rather than always appending a new one.
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
      pendingFocus.current = { key: targetKey, field: diff > 0 ? 'credit' : 'debit' }
      return ensureTrailingBlank(next, lastFocusedKey.current)
    })
  }

  function clear() {
    setDate(today)
    setScenarioId(firstScenarioId)
    setDescription('')
    setReference('')
    setPayeeId('')
    setTagsCsv('')
    setTemplateId('')
    setLines([makeBlankLine(), makeBlankLine()])
    setError(null)
    pendingFocus.current = null
    descriptionRef.current?.focus()
  }

  function loadTemplate(tpl: Template) {
    setDescription(tpl.description || '')
    setReference(tpl.reference || '')
    setPayeeId(tpl.payee_id != null ? String(tpl.payee_id) : '')
    setTagsCsv((tpl.tags || []).join(','))
    const loaded = tpl.lines.map((ln) => ({
      ...makeBlankLine(),
      account: ln.code,
      debit: ln.debit || '',
      credit: ln.credit || '',
      memo: ln.memo || '',
    }))
    setLines(ensureTrailingBlank(loaded, null))
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
  const scenarioObj = scenarios.find((s) => s.id === scenarioId)
  const enforcing = scenarioObj ? scenarioObj.enforce_balance : true
  const postDisabled = posting || (enforcing ? !balanced : totals.deb === 0 && totals.cre === 0)
  const balanceMsg = balanced
    ? 'Balanced — ready to post.'
    : enforcing
      ? 'Debits and credits must be equal before this entry can post.'
      : 'This scenario accepts single-sided entries; balance is optional.'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setPosting(true)
    const used = lines.filter(isLineUsed)
    const { data, error: err } = await client.POST('/entries', {
      body: {
        entry_date: date || undefined,
        scenario_id: scenarioId,
        description,
        reference: reference || undefined,
        payee_id: payeeId ? Number(payeeId) : undefined,
        tags: tagsCsv,
        lines: used.map((l) => ({ account: l.account, debit: l.debit, credit: l.credit, memo: l.memo || undefined })),
      },
    })
    setPosting(false)
    if (err) {
      setError(errorDetail(err, 'Could not reach the server — check your connection and try again.'))
      return
    }
    const body = data as unknown as { entry_id: string }
    clear()
    if (detailsRef.current) detailsRef.current.open = false
    onPosted(body.entry_id)
  }

  // e.code, not e.key — see app.js's own comment on why (macOS Option
  // remaps letters, so a "n"/"d"/... check against e.key silently never
  // matches there).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!e.altKey) return
      if (e.code === 'KeyN') {
        e.preventDefault()
        addRow()
      } else if (e.code === 'KeyD') {
        e.preventDefault()
        distribute()
      } else if (e.code === 'KeyE') {
        e.preventDefault()
        const details = detailsRef.current
        if (!details) return
        if (details.open) {
          details.open = false
        } else {
          details.open = true
          const first = tableRef.current?.querySelector(
            'tr[data-row-key] .combobox-input, tr[data-row-key] input',
          ) as HTMLElement | null
          first?.focus()
        }
      } else if (e.code === 'KeyS') {
        e.preventDefault()
        formRef.current?.requestSubmit() // no-op while disabled, same as clicking Post by hand
      } else if (e.code === 'KeyC') {
        e.preventDefault()
        clear()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- addRow/distribute/clear close over state via setState updaters, not stale reads
  }, [])

  return (
    <details className="entry entry-new" id="new-entry-panel" ref={detailsRef}>
      <summary>+ New entry ({altLabel('E')})</summary>
      <div className="lines">
        {templates.length > 0 && (
          <div className="bar" style={{ marginBottom: '0.8rem' }}>
            <label className="field" style={{ maxWidth: '20rem' }}>
              Load template
              <Combobox
                options={[
                  { value: '', label: 'Choose a template' },
                  ...templates.map((t) => ({ value: String(t.id), label: t.name })),
                ]}
                value={templateId}
                onChange={(v) => {
                  setTemplateId(v)
                  const tpl = templates.find((t) => String(t.id) === v)
                  if (tpl) loadTemplate(tpl)
                }}
              />
            </label>
          </div>
        )}

        {error && <div className="flash flash-err">{error}</div>}

        <form onSubmit={submit} ref={formRef} id="entry-form">
          <div className="bar">
            <label className="field">
              Date
              <DatePicker value={date} onChange={setDate} />
            </label>
            <label className="field">
              Scenario
              <Combobox
                options={eligibleScenarios.map((s) => ({
                  value: String(s.id),
                  label: `${s.code} — ${s.name}${s.enforce_balance ? '' : ' (single-sided OK)'}`,
                }))}
                value={String(scenarioId)}
                onChange={(v) => setScenarioId(Number(v))}
              />
            </label>
            <label className="field" style={{ flex: 1, minWidth: '16rem' }}>
              Description
              <input
                ref={descriptionRef}
                type="text"
                required
                placeholder="e.g. August rent"
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

          <div className={'balance-bar' + (balanced ? ' balanced' : ' unbalanced')} id="balance-bar">
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
              <button type="submit" disabled={postDisabled}>
                Post entry ({altLabel('S')})
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
            <button type="button" className="quiet" title="Clear every field on this form" onClick={clear}>
              Clear ({altLabel('C')})
            </button>
          </p>
        </form>
      </div>
    </details>
  )
}
