import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useConfirm } from '../widgets/confirmContext'
import MergeDialog from '../widgets/MergeDialog'
import { useSelectMode } from '../widgets/useSelectMode'

// Ported from app/templates/payees.html + entity-manage.js (Phase 4.2) —
// same Management/CRUD shape TagsPage.tsx (Phase 3.2) already ported,
// with three real differences from Tags rather than a shared abstraction
// (matching TagsPage.tsx's own choice not to factor the entity-specific
// half out — see useSelectMode.ts's own comment on why only the
// Select/Merge half is shared):
//
// 1. Name is `maxlength="80"` here, not 40 (payees.html's own input).
// 2. The entry-count cell is a real drill-through link to the Journal
//    (`/app/entries?payee=...`) — legacy's own `entry_link` macro,
//    unreachable from TagsPage.tsx (Phase 3.2, predates Journal
//    existing at all) but real now that JournalPage.tsx (Phase 3.4)
//    already reads `?payee=`. No `back=` param: JournalPage.tsx's own
//    Phase 3.4 comment defers that until something in this rebuild
//    actually sets it, and this is that "something," except it still
//    doesn't — same reasoning, revisit together.
// 3. No quick-create route rendered here — `POST /payees/quick-create`
//    exists for the Journal's own Payee combobox (`usePayees.ts`'s
//    first caller), not this table.
interface Payee {
  id: number
  name: string
  is_active: boolean
  entry_count: number
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

export default function PayeesPage() {
  const [payees, setPayees] = useState<Payee[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  const [addName, setAddName] = useState('')
  const [addErr, setAddErr] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const addPanelRef = useRef<HTMLDetailsElement>(null)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const editInputRef = useRef<HTMLInputElement>(null)

  const [mergeOpen, setMergeOpen] = useState(false)
  const selectAllRef = useRef<HTMLInputElement>(null)

  const confirm = useConfirm()

  const reload = useCallback(async () => {
    const { data } = await client.GET('/payees')
    if (data) setPayees(data as unknown as Payee[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/payees').then(({ data }) => {
      if (!cancelled && data) setPayees(data as unknown as Payee[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (editingId === null) return
    editInputRef.current?.focus()
    editInputRef.current?.select()
  }, [editingId])

  const select = useSelectMode((payees ?? []).map((p) => p.id), selectAllRef)

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    setAdding(true)
    setAddErr(null)
    const { data, error } = await client.POST('/payees', { body: { name: addName } })
    setAdding(false)
    if (error) {
      setAddErr(errorDetail(error, 'Could not add payee'))
      return
    }
    setAddName('')
    if (addPanelRef.current) addPanelRef.current.open = false
    setFlash({ ok: `Payee “${(data as unknown as { name: string }).name}” added` })
    await reload()
  }

  function startEdit(p: Payee) {
    setEditingId(p.id)
    setEditValue(p.name)
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function submitRename(e: FormEvent, id: number) {
    e.preventDefault()
    const { data, error } = await client.POST('/payees/{payee_id}/rename', {
      params: { path: { payee_id: id } },
      body: { name: editValue },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not rename payee') })
      return
    }
    setEditingId(null)
    setFlash({ ok: `Renamed to “${(data as unknown as { name: string }).name}”` })
    await reload()
  }

  async function toggleActive(p: Payee) {
    const { error } = await client.POST('/payees/{payee_id}/toggle-active', {
      params: { path: { payee_id: p.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not update payee') })
      return
    }
    setFlash({ ok: p.is_active ? `“${p.name}” archived` : `“${p.name}” unarchived` })
    await reload()
  }

  async function deletePayee(p: Payee) {
    const ok = await confirm(
      `Delete payee “${p.name}”? Entries that used it will lose the payee label — this can't be undone.`,
      { okLabel: 'Delete', danger: true },
    )
    if (!ok) return
    const { error } = await client.POST('/payees/{payee_id}/delete', {
      params: { path: { payee_id: p.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not delete payee') })
      return
    }
    setFlash({ ok: `“${p.name}” deleted` })
    await reload()
  }

  const checkedPayees = (payees ?? []).filter((p) => select.checkedIds.has(p.id))

  async function confirmMerge(targetName: string) {
    const [survivor, ...rest] = checkedPayees
    const { data, error } = await client.POST('/payees/merge', {
      body: { payee_ids: [survivor.id, ...rest.map((p) => p.id)], target_name: targetName },
    })
    setMergeOpen(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not merge payees') })
      return
    }
    const body = data as unknown as { merged: number; entries_affected: number }
    setFlash({ ok: `Merged ${body.merged} payees into “${targetName}” (${body.entries_affected} entries affected)` })
    select.toggleSelectMode()
    await reload()
  }

  if (payees === null) return <p>Loading…</p>

  return (
    <>
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
        <button
          type="button"
          className="quiet"
          disabled={select.checkedIds.size < 2}
          onClick={() => setMergeOpen(true)}
        >
          Merge
        </button>
      </p>

      <details className="entry entry-new quiet" ref={addPanelRef}>
        <summary>+ Add payee</summary>
        <div className="lines">
          {addErr && <div className="flash flash-err">{addErr}</div>}
          <form className="bar" onSubmit={handleAdd}>
            <label className="field" style={{ flex: 1, minWidth: '16rem' }}>
              Name
              <input
                type="text"
                required
                placeholder="e.g. Whole Foods"
                maxLength={80}
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
              />
            </label>
            <button type="submit" disabled={adding}>
              Add payee
            </button>
          </form>
        </div>
      </details>

      <table className="ledger entity-table">
        <thead>
          <tr>
            <th className="select-only"></th>
            <th>Name</th>
            <th className="num">Entries</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {payees.length === 0 && (
            <tr>
              <td colSpan={5} className="dim">
                No payees yet.
              </td>
            </tr>
          )}
          {payees.map((p) => (
            <tr key={p.id} className={p.is_active ? undefined : 'inactive'}>
              <td className="select-only">
                <input
                  type="checkbox"
                  checked={select.checkedIds.has(p.id)}
                  onChange={() => select.toggleChecked(p.id)}
                />
              </td>
              <td>
                {editingId === p.id ? (
                  <form
                    className="entity-rename-form"
                    onSubmit={(e) => submitRename(e, p.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') cancelEdit()
                    }}
                  >
                    <input
                      ref={editInputRef}
                      type="text"
                      className="entity-rename-input"
                      required
                      maxLength={80}
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                    />
                  </form>
                ) : (
                  <span className="entity-name-label">{p.name}</span>
                )}
              </td>
              <td className="num mono">
                {p.entry_count ? (
                  <Link className="amount-link" to={`/app/entries?payee=${encodeURIComponent(p.name)}`}>
                    {p.entry_count}
                  </Link>
                ) : (
                  p.entry_count
                )}
              </td>
              <td className="dim">{p.is_active ? 'active' : 'archived'}</td>
              <td className="actions">
                {editingId === p.id ? null : (
                  <button type="button" className="quiet" onClick={() => startEdit(p)}>
                    Edit
                  </button>
                )}
                <button type="button" className="quiet" onClick={() => toggleActive(p)}>
                  {p.is_active ? 'Archive' : 'Unarchive'}
                </button>
                <button type="button" className="quiet" onClick={() => deletePayee(p)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <MergeDialog
        open={mergeOpen}
        count={checkedPayees.length}
        labelPlural="payees"
        initialName={checkedPayees[0]?.name ?? ''}
        onCancel={() => setMergeOpen(false)}
        onConfirm={confirmMerge}
      />
    </>
  )
}
