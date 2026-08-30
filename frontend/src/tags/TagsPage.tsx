import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useConfirm } from '../widgets/confirmContext'
import MergeDialog from '../widgets/MergeDialog'
import { useSelectMode } from '../widgets/useSelectMode'

// Ported from app/templates/tags.html + app/static/entity-manage.js
// (Phase 3.2) — the Management/CRUD archetype's first real screen. Same
// Select/Merge/+Add/table/Status/Archive shape the legacy template's own
// comment describes, driven here by React state instead of a shared
// vanilla-JS file plus data-* attributes.
//
// GET /tags's own response is a plain `dict` list (`modules/reference/
// router.py`), so openapi-fetch can only type it as
// `{[key: string]: unknown}[]` — same gap `auth/SessionProvider.tsx`'s own
// Phase 3.1 comment already documents for `/login`/`/me`, cast through
// this local interface instead.
interface Tag {
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

export default function TagsPage() {
  const [tags, setTags] = useState<Tag[] | null>(null)
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

  // `reload` (below) is the version every write handler calls after its
  // own mutation lands — always user-triggered, so there's no unmounted-
  // component race to guard against (same reasoning SessionProvider.tsx's
  // own `login`/`logout` give for not needing a `cancelled` flag either).
  // The *initial* fetch on mount is deliberately not just `reload()`
  // called from a bare `useEffect(() => { reload() }, [reload])` — oxlint's
  // `react(set-state-in-effect)` flags that shape (a named function whose
  // own body sets state, invoked directly from an effect) even though the
  // `setTags` call inside it is genuinely async, not synchronous. Inlined
  // here instead, matching `useAppConfig.ts`'s own already-clean
  // fetch-on-mount shape exactly, `cancelled` guard included.
  const reload = useCallback(async () => {
    const { data } = await client.GET('/tags')
    if (data) setTags(data as unknown as Tag[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/tags').then(({ data }) => {
      if (!cancelled && data) setTags(data as unknown as Tag[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  // Focus + select the row's own rename input the moment it appears —
  // entity-manage.js's own `input.focus(); input.select();`, run once per
  // entry into edit mode (not on every keystroke — this effect is keyed
  // on `editingId`, not `editValue`, which matters: an inline ref
  // callback here instead would re-fire — and re-select all the typed
  // text — on every render the input's own onChange causes).
  useEffect(() => {
    if (editingId === null) return
    editInputRef.current?.focus()
    editInputRef.current?.select()
  }, [editingId])

  const select = useSelectMode((tags ?? []).map((t) => t.id), selectAllRef)

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    setAdding(true)
    setAddErr(null)
    const { data, error } = await client.POST('/tags', { body: { name: addName } })
    setAdding(false)
    if (error) {
      setAddErr(errorDetail(error, 'Could not add tag'))
      return
    }
    setAddName('')
    if (addPanelRef.current) addPanelRef.current.open = false
    // The server's own returned name, not the raw input — `parse_tags`
    // (domain/entry.py) lowercases/trims, so "Groceries" as typed and
    // "groceries" as actually stored can genuinely differ.
    setFlash({ ok: `Tag “${(data as unknown as { name: string }).name}” added` })
    await reload()
  }

  function startEdit(t: Tag) {
    setEditingId(t.id)
    setEditValue(t.name)
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function submitRename(e: FormEvent, id: number) {
    e.preventDefault()
    const { data, error } = await client.POST('/tags/{tag_id}/rename', {
      params: { path: { tag_id: id } },
      body: { name: editValue },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not rename tag') })
      return
    }
    setEditingId(null)
    setFlash({ ok: `Renamed to “${(data as unknown as { name: string }).name}”` })
    await reload()
  }

  async function toggleActive(t: Tag) {
    const { error } = await client.POST('/tags/{tag_id}/toggle-active', {
      params: { path: { tag_id: t.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not update tag') })
      return
    }
    setFlash({ ok: t.is_active ? `“${t.name}” archived` : `“${t.name}” unarchived` })
    await reload()
  }

  async function deleteTag(t: Tag) {
    const ok = await confirm(
      `Delete tag “${t.name}”? It'll be removed from every entry that has it — this can't be undone.`,
      { okLabel: 'Delete', danger: true },
    )
    if (!ok) return
    const { error } = await client.POST('/tags/{tag_id}/delete', {
      params: { path: { tag_id: t.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not delete tag') })
      return
    }
    setFlash({ ok: `“${t.name}” deleted` })
    await reload()
  }

  // Survivor is whichever checked row sorts first in the table (matching
  // GET /tags's own `ORDER BY t.name`), not whichever checkbox was
  // clicked first — same "DOM order, not click order" rule entity-
  // manage.js's own `Array.from(table.querySelectorAll(...))` read gave
  // for free and a plain Set can't answer on its own.
  const checkedTags = (tags ?? []).filter((t) => select.checkedIds.has(t.id))

  async function confirmMerge(targetName: string) {
    const [survivor, ...rest] = checkedTags
    const { data, error } = await client.POST('/tags/merge', {
      body: { tag_ids: [survivor.id, ...rest.map((t) => t.id)], target_name: targetName },
    })
    setMergeOpen(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not merge tags') })
      return
    }
    const body = data as unknown as { merged: number; entries_affected: number }
    setFlash({ ok: `Merged ${body.merged} tags into “${targetName}” (${body.entries_affected} entries affected)` })
    select.toggleSelectMode()
    await reload()
  }

  if (tags === null) return <p>Loading…</p>

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#tags" className="help-icon" aria-label="How this works" title="How this works">
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
          <input
            ref={selectAllRef}
            type="checkbox"
            onChange={select.toggleSelectAll}
          />
          select all
        </label>
        {/* No `select-only` here — matches tags.html exactly: unlike the
            "select all" checkbox, Merge is always in the DOM, just
            `disabled` until 2+ rows are checked (which can only happen
            once Select mode has revealed the per-row checkboxes to check
            in the first place). Ported as-is, not "fixed" to hide it
            outside Select mode too, per REBUILD.md decision 4. */}
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
        <summary>+ Add tag</summary>
        <div className="lines">
          {addErr && <div className="flash flash-err">{addErr}</div>}
          <form className="bar" onSubmit={handleAdd}>
            <label className="field" style={{ flex: 1, minWidth: '16rem' }}>
              Name
              <input
                type="text"
                required
                placeholder="e.g. groceries"
                maxLength={40}
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
              />
            </label>
            <button type="submit" disabled={adding}>
              Add tag
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
          {tags.length === 0 && (
            <tr>
              <td colSpan={5} className="dim">
                No tags yet.
              </td>
            </tr>
          )}
          {tags.map((t) => (
            <tr key={t.id} className={t.is_active ? undefined : 'inactive'}>
              <td className="select-only">
                <input
                  type="checkbox"
                  checked={select.checkedIds.has(t.id)}
                  onChange={() => select.toggleChecked(t.id)}
                />
              </td>
              <td>
                {editingId === t.id ? (
                  <form
                    className="entity-rename-form"
                    onSubmit={(e) => submitRename(e, t.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') cancelEdit()
                    }}
                  >
                    <input
                      ref={editInputRef}
                      type="text"
                      className="entity-rename-input"
                      required
                      maxLength={40}
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                    />
                  </form>
                ) : (
                  <span className="entity-name-label">{t.name}</span>
                )}
              </td>
              {/* Entry count stays plain text, not legacy's amount-link
                  through to a filtered Journal — /app/entries doesn't
                  exist yet (Phase 3.4), same "don't reach into a screen
                  that doesn't exist yet" reasoning every prior phase
                  already applied to modules with no live counterpart. */}
              <td className="num mono">{t.entry_count}</td>
              <td className="dim">{t.is_active ? 'active' : 'archived'}</td>
              <td className="actions">
                {editingId === t.id ? null : (
                  <button type="button" className="quiet" onClick={() => startEdit(t)}>
                    Edit
                  </button>
                )}
                <button type="button" className="quiet" onClick={() => toggleActive(t)}>
                  {t.is_active ? 'Archive' : 'Unarchive'}
                </button>
                <button type="button" className="quiet" onClick={() => deleteTag(t)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <MergeDialog
        open={mergeOpen}
        count={checkedTags.length}
        labelPlural="tags"
        initialName={checkedTags[0]?.name ?? ''}
        onCancel={() => setMergeOpen(false)}
        onConfirm={confirmMerge}
      />
    </>
  )
}
