import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useConfirm } from '../widgets/confirmContext'

// No select/merge, no edit-mode toggle: rename is a permanently-visible
// text input + Save button right in the row, not TagsPage.tsx/
// PayeesPage.tsx's click-to-edit pattern, so this page carries no
// `editingId` state and doesn't reach for `useSelectMode.ts`/
// `MergeDialog.tsx`.
interface AccountLevelRow {
  id: number
  name: string
  depth: number
  scenario_count: number
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

export default function AccountLevelsPage() {
  const [levels, setLevels] = useState<AccountLevelRow[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [names, setNames] = useState<Record<number, string>>({})

  const [newDepth, setNewDepth] = useState('1')
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  const confirm = useConfirm()

  const reload = useCallback(async () => {
    const { data } = await client.GET('/account-levels')
    if (data) {
      const rows = data as unknown as AccountLevelRow[]
      setLevels(rows)
      setNames(Object.fromEntries(rows.map((lv) => [lv.id, lv.name])))
      // `next_depth = max(depths, default=0) + 1` — computed here from
      // the same list rather than a dedicated route, since no backend
      // route returns it.
      setNewDepth(String(Math.max(0, ...rows.map((lv) => lv.depth)) + 1))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/account-levels').then(({ data }) => {
      if (cancelled || !data) return
      const rows = data as unknown as AccountLevelRow[]
      setLevels(rows)
      setNames(Object.fromEntries(rows.map((lv) => [lv.id, lv.name])))
      setNewDepth(String(Math.max(0, ...rows.map((lv) => lv.depth)) + 1))
    })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    const { data, error } = await client.POST('/account-levels', {
      body: { name: newName, depth: Number(newDepth) },
    })
    setCreating(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not create level') })
      return
    }
    setFlash({ ok: `Level “${(data as unknown as { name: string }).name}” created` })
    setNewName('')
    await reload()
  }

  async function submitRename(e: FormEvent, lv: AccountLevelRow) {
    e.preventDefault()
    const name = names[lv.id] ?? lv.name
    const { data, error } = await client.POST('/account-levels/{level_id}/rename', {
      params: { path: { level_id: lv.id } },
      body: { name },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not rename level') })
      return
    }
    setFlash({ ok: `Renamed to “${(data as unknown as { name: string }).name}”` })
    await reload()
  }

  async function deleteLevel(lv: AccountLevelRow) {
    const ok = await confirm(`Delete level ${lv.name}?`, { okLabel: 'Delete', danger: true })
    if (!ok) return
    const { error } = await client.POST('/account-levels/{level_id}/delete', {
      params: { path: { level_id: lv.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not delete level') })
      return
    }
    setFlash({ ok: `“${lv.name}” deleted` })
    await reload()
  }

  if (levels === null) return <p>Loading…</p>

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#accounts" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <table className="ledger">
        <thead>
          <tr>
            <th>Depth</th>
            <th>Name</th>
            <th className="num">Scenarios using it</th>
            <th></th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {levels.length === 0 && (
            <tr>
              <td colSpan={5} className="dim">
                No levels yet.
              </td>
            </tr>
          )}
          {levels.map((lv) => (
            <tr key={lv.id}>
              <td className="mono dim">{lv.depth}</td>
              <td>
                <form className="bar" onSubmit={(e) => submitRename(e, lv)}>
                  <input
                    type="text"
                    required
                    style={{ maxWidth: '16rem' }}
                    value={names[lv.id] ?? lv.name}
                    onChange={(e) => setNames((prev) => ({ ...prev, [lv.id]: e.target.value }))}
                  />
                  <button type="submit" className="quiet">
                    Save
                  </button>
                </form>
              </td>
              <td className="num mono">{lv.scenario_count}</td>
              <td colSpan={2}>
                <button type="button" className="quiet" onClick={() => deleteLevel(lv)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="panel">
        <h2>New level</h2>
        <form className="grid-form" onSubmit={handleCreate}>
          <label className="field" style={{ maxWidth: '8rem' }}>
            Depth
            <input
              type="number"
              min={1}
              required
              value={newDepth}
              onChange={(e) => setNewDepth(e.target.value)}
            />
          </label>
          <label className="field">
            Name
            <input
              type="text"
              required
              placeholder="e.g. Account Detail"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>
          <button type="submit" disabled={creating}>
            Create level
          </button>
        </form>
        <p className="dim small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          Depth must match how deep an account actually sits under its parents to mean anything —
          e.g. depth 3 is Assets → Bank → Checking. Levels don't have to be contiguous or cover
          every depth your chart uses.
        </p>
      </div>
    </>
  )
}
