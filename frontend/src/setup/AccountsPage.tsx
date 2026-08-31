import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import type { Account, AccountType } from '../api/useAccounts'
import { useAccountLevels } from '../api/useAccountLevels'
import { useConfirm } from '../widgets/confirmContext'

// The Management/CRUD archetype (UI_CONSISTENCY_AUDIT.md §2e/§4b groups
// Accounts with Payees/Tags/Scenarios/Levels/Scheduled/Templates), but
// the only one of that family shaped as a two-column level browser over
// a collapsible tree rather than a flat table. Two distinct write paths
// drive it: `POST /accounts` (the bottom "New account" panel, an exact
// code typed in) and `POST /accounts/quick-create` (the tree's own
// inline "+" gap rows, a code generated server-side) — see
// `modules/reference/schemas.py`'s own `CreateAccountRequest`/
// `QuickCreateAccountRequest` docstrings for why both still exist.
//
// "Mark as cash" / "Unmark cash" is ported verbatim despite
// UI_CONSISTENCY_AUDIT.md §3.9 flagging it as unclear wording
// (BACKLOG.md) — that's an *open, unshipped* backlog item on `master`,
// not something this branch's own porting work is licensed to resolve
// on the side; §4a's wording unification (Archive/Unarchive) *is*
// already shipped on `master` and is what this page ports as-is.

const ACCOUNT_TYPES: AccountType[] = ['asset', 'liability', 'equity', 'income', 'expense']
const TYPE_LABELS: Record<AccountType, string> = {
  asset: 'Assets',
  liability: 'Liabilities',
  equity: 'Equity',
  income: 'Income',
  expense: 'Expenses',
}

const STORAGE_KEY = 'postwarden-accounts-collapsed'

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// Every summary account starts collapsed on a browser's first visit
// (nothing in localStorage yet) — true tree browsing, not "everything
// already expanded" — and exactly whatever was there before once a
// person has customized it.
function loadCollapsed(accounts: Account[]): Set<number> {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored !== null) {
    try {
      return new Set(JSON.parse(stored))
    } catch {
      return new Set()
    }
  }
  return new Set(accounts.filter((a) => !a.is_postable).map((a) => a.id))
}

// Mirrors `domain/accounts.py`'s own `accounts_with_gaps` shape — a "+"
// gap sits before every account row, plus one trailing gap after the
// last row. Keyed by array position (`gap-${account.id}` isn't unique:
// the gap immediately before the last account and the trailing gap both
// track that same account via `track_id`), not by `track_id` itself,
// since two gaps can share one.
type Row = { kind: 'gap'; key: string; trackId: number | null } | { kind: 'account'; key: string; account: Account }

function buildRows(sorted: Account[]): Row[] {
  const rows: Row[] = []
  let lastId: number | null = null
  for (const a of sorted) {
    rows.push({ kind: 'gap', key: `gap-before-${a.id}`, trackId: a.id })
    rows.push({ kind: 'account', key: `acct-${a.id}`, account: a })
    lastId = a.id
  }
  rows.push({ kind: 'gap', key: 'gap-end', trackId: lastId })
  return rows
}

// Nearest visible account row in one direction from a gap's own index,
// skipping other gaps and anything currently hidden by a collapsed
// ancestor.
function nearestAccount(rows: Row[], index: number, dir: 1 | -1, hidden: Map<number, boolean>): Account | null {
  let i = index + dir
  while (i >= 0 && i < rows.length) {
    const row = rows[i]
    if (row.kind === 'account' && !hidden.get(row.account.id)) return row.account
    i += dir
  }
  return null
}

export default function AccountsPage() {
  const levels = useAccountLevels()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [selectedLevelId, setSelectedLevelId] = useState<number | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const collapsedInit = useRef(false)
  const confirm = useConfirm()

  // New-account panel
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [accountType, setAccountType] = useState<AccountType>('asset')
  const [parentId, setParentId] = useState('')
  const [isPostable, setIsPostable] = useState(true)
  const [isCashflow, setIsCashflow] = useState(false)
  const [creating, setCreating] = useState(false)

  // Inline "+" gap-add form — at most one open at a time.
  const [openGapKey, setOpenGapKey] = useState<string | null>(null)
  const [gapName, setGapName] = useState('')
  const [gapParentId, setGapParentId] = useState('')
  const [gapType, setGapType] = useState<AccountType>('asset')
  const [gapPostable, setGapPostable] = useState(true)
  const [gapSaving, setGapSaving] = useState(false)
  const openGapRowRef = useRef<HTMLTableRowElement>(null)
  const gapNameRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(async () => {
    const { data } = await client.GET('/accounts')
    if (data) setAccounts(data as unknown as Account[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/accounts').then(({ data }) => {
      if (cancelled || !data) return
      setAccounts(data as unknown as Account[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  // Seeded once, from whatever the very first successful fetch returned
  // — a later `reload()` (after creating/toggling an account) must not
  // reset a person's own collapse choices back to the localStorage/
  // default computation.
  useEffect(() => {
    if (accounts && !collapsedInit.current) {
      collapsedInit.current = true
      setCollapsed(loadCollapsed(accounts))
    }
  }, [accounts])

  useEffect(() => {
    if (collapsedInit.current) localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(collapsed)))
  }, [collapsed])

  const accountById = useMemo(() => new Map((accounts ?? []).map((a) => [a.id, a])), [accounts])

  const hiddenById = useMemo(() => {
    const m = new Map<number, boolean>()
    function hasCollapsedAncestor(a: Account): boolean {
      let ancestorId = a.parent_id
      while (ancestorId != null) {
        if (collapsed.has(ancestorId)) return true
        const ancestor = accountById.get(ancestorId)
        ancestorId = ancestor ? ancestor.parent_id : null
      }
      return false
    }
    for (const a of accounts ?? []) m.set(a.id, hasCollapsedAncestor(a))
    return m
  }, [accounts, accountById, collapsed])

  const topLevelTypesTaken = useMemo(
    () => new Set((accounts ?? []).filter((a) => a.parent_id == null).map((a) => a.account_type)),
    [accounts],
  )

  const selectedLevel = selectedLevelId != null ? (levels ?? []).find((lv) => lv.id === selectedLevelId) : undefined
  const displayAccounts = selectedLevel ? (accounts ?? []).filter((a) => a.depth === selectedLevel.depth) : null
  // `v_dim_account` already arrives `ORDER BY sort_path` (repository.py's
  // no-`level_id` branch) — the same order the tree needs, so no
  // client-side re-sort here.
  const rows = useMemo(() => buildRows(accounts ?? []), [accounts])

  // A warning, not a block: a second top-level Asset/Liability/Equity/Income
  // account is a legitimate power-user pattern (splitting "Personal"
  // from "Business" assets, say), Expense is deliberately exempt
  // (db/seed.sql's own 5000-9000 expects several top-level roots), and
  // nothing in the schema itself enforces "exactly one" either way.
  async function confirmTopLevel(parentValue: string, type: AccountType): Promise<boolean> {
    if (parentValue || type === 'expense' || !topLevelTypesTaken.has(type)) return true
    const label = TYPE_LABELS[type]
    return confirm(
      `PostWarden expects one top-level ${label} account, and you already have one. ` +
        `Add another top-level ${label} account anyway?`,
    )
  }

  function toggleCollapse(a: Account) {
    if (a.is_postable) return
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(a.id)) next.delete(a.id)
      else next.add(a.id)
      return next
    })
  }

  async function toggleActive(a: Account) {
    const { error } = await client.POST('/accounts/{account_id}/toggle-active', {
      params: { path: { account_id: a.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not update account') })
      return
    }
    setFlash({ ok: 'Account updated' })
    await reload()
  }

  async function toggleCashflow(a: Account) {
    const { error } = await client.POST('/accounts/{account_id}/toggle-cashflow', {
      params: { path: { account_id: a.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not update account') })
      return
    }
    setFlash({ ok: 'Account updated' })
    await reload()
  }

  async function handleCreateAccount(e: FormEvent) {
    e.preventDefault()
    const ok = await confirmTopLevel(parentId, accountType)
    if (!ok) return
    setCreating(true)
    const { data, error } = await client.POST('/accounts', {
      body: {
        code: code.trim(),
        name: name.trim(),
        account_type: accountType,
        parent_id: parentId ? Number(parentId) : null,
        is_postable: isPostable,
        is_cashflow: isCashflow,
      },
    })
    setCreating(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not create account') })
      return
    }
    const created = data as unknown as { code: string; name: string }
    setFlash({ ok: `Account ${created.code} — ${created.name} created` })
    setCode('')
    setName('')
    setParentId('')
    setIsPostable(true)
    setIsCashflow(false)
    await reload()
  }

  // Computes the parent/type default from whichever two rows are
  // currently visible right around this gap, not the full flat list (a
  // collapsed summary account's own hidden children must never be
  // "the next row").
  function openGapForm(gapIndex: number) {
    const prev = nearestAccount(rows, gapIndex, -1, hiddenById)
    const next = nearestAccount(rows, gapIndex, 1, hiddenById)
    let newParentId = ''
    let type: AccountType = next ? next.account_type : 'asset'
    if (prev) {
      // An empty summary account (no children anywhere, not just visible
      // ones) is otherwise indistinguishable here from "insert a sibling
      // after it" — default to "first child of prev" in that case: an
      // empty summary account's whole reason to exist is to hold
      // children.
      const prevIsEmptySummary = !prev.is_postable && !(accounts ?? []).some((a) => a.parent_id === prev.id)
      if (prevIsEmptySummary || (next && next.parent_id === prev.id)) {
        newParentId = String(prev.id)
      } else {
        newParentId = prev.parent_id != null ? String(prev.parent_id) : ''
      }
      type = prev.account_type
    }
    setGapParentId(newParentId)
    setGapType(type)
    setGapName('')
    setGapPostable(true)
    setOpenGapKey(rows[gapIndex].key)
  }

  useEffect(() => {
    if (openGapKey) gapNameRef.current?.focus()
  }, [openGapKey])

  // Outside click closes the form — same as every other popover in this
  // app (combobox, the date picker, the confirm dialog's own backdrop).
  useEffect(() => {
    if (!openGapKey) return
    function onDocMouseDown(e: MouseEvent) {
      if (openGapRowRef.current && !openGapRowRef.current.contains(e.target as Node)) setOpenGapKey(null)
    }
    document.addEventListener('mousedown', onDocMouseDown, true)
    return () => document.removeEventListener('mousedown', onDocMouseDown, true)
  }, [openGapKey])

  async function submitGapForm(e: FormEvent) {
    e.preventDefault()
    const trimmed = gapName.trim()
    if (!trimmed) return
    const ok = await confirmTopLevel(gapParentId, gapType)
    if (!ok) return
    setGapSaving(true)
    const { data, error } = await client.POST('/accounts/quick-create', {
      body: {
        name: trimmed,
        parent_id: gapParentId ? Number(gapParentId) : null,
        account_type: gapParentId ? null : gapType,
        is_postable: gapPostable,
      },
    })
    setGapSaving(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not create account') })
      return
    }
    const created = data as unknown as { code: string; name: string }
    setFlash({ ok: `Account ${created.code} — ${created.name} created` })
    setOpenGapKey(null)
    await reload()
  }

  if (accounts === null || levels === null) return <p>Loading…</p>

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#accounts" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <div className="two-col">
        <nav className="side-nav">
          <button
            type="button"
            className={selectedLevelId === null ? 'active' : undefined}
            onClick={() => setSelectedLevelId(null)}
          >
            All levels
          </button>
          {levels.map((lv) => (
            <button
              key={lv.id}
              type="button"
              className={selectedLevelId === lv.id ? 'active' : undefined}
              style={{ paddingLeft: `${0.5 + (Math.min(lv.depth, 6) - 1) * 1}rem` }}
              onClick={() => setSelectedLevelId(lv.id)}
            >
              {lv.name}
            </button>
          ))}
          <Link to="/app/account-levels" className="dim" style={{ marginTop: '0.4rem' }}>
            Manage levels…
          </Link>
        </nav>

        <div className="two-col-main">
          {selectedLevel ? (
            <>
              <p className="page-sub">
                Showing only <strong>{selectedLevel.name}</strong> — every account sitting exactly at depth{' '}
                {selectedLevel.depth}, wherever it lives in the tree.
              </p>
              <table className="ledger accounts-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Account</th>
                    <th>Type</th>
                    <th>Postable</th>
                    <th>Cash flow</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {displayAccounts && displayAccounts.length === 0 && (
                    <tr>
                      <td colSpan={6} className="dim">
                        No accounts at this level yet.
                      </td>
                    </tr>
                  )}
                  {displayAccounts?.map((a) => (
                    <tr key={a.id} className={a.is_active ? undefined : 'inactive'}>
                      <td className="mono dim">{a.code}</td>
                      <td>
                        {a.name} {a.parent_path && <span className="dim small">{a.parent_path}</span>}
                      </td>
                      <td className="dim">{TYPE_LABELS[a.account_type]}</td>
                      <td className="dim">{a.is_postable ? 'leaf' : 'summary'}</td>
                      <td className="dim">{a.is_cashflow ? 'cash' : ''}</td>
                      <td>
                        <button type="button" className="quiet" onClick={() => toggleActive(a)}>
                          {a.is_active ? 'Archive' : 'Unarchive'}
                        </button>
                        <button type="button" className="quiet" onClick={() => toggleCashflow(a)}>
                          {a.is_cashflow ? 'Unmark cash' : 'Mark as cash'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <table className="ledger accounts-table" id="accounts-tree">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Account</th>
                  <th>Type</th>
                  <th>Postable</th>
                  <th>Cash flow</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="accounts-body">
                {rows.map((row, i) =>
                  row.kind === 'gap' ? (
                    <tr
                      key={row.key}
                      className={openGapKey === row.key ? 'add-gap open' : 'add-gap'}
                      hidden={row.trackId != null ? hiddenById.get(row.trackId) : false}
                      ref={openGapKey === row.key ? openGapRowRef : undefined}
                    >
                      <td colSpan={6}>
                        {openGapKey === row.key ? (
                          <form className="add-gap-form" onSubmit={submitGapForm}>
                            {!gapParentId && (
                              <select
                                className="add-gap-type"
                                value={gapType}
                                onChange={(e) => setGapType(e.target.value as AccountType)}
                              >
                                {ACCOUNT_TYPES.map((t) => (
                                  <option key={t} value={t}>
                                    {TYPE_LABELS[t]}
                                  </option>
                                ))}
                              </select>
                            )}
                            <input
                              ref={gapNameRef}
                              type="text"
                              placeholder="Category name"
                              required
                              value={gapName}
                              onChange={(e) => setGapName(e.target.value)}
                            />
                            <label className="checkline">
                              <input
                                type="checkbox"
                                checked={gapPostable}
                                onChange={(e) => setGapPostable(e.target.checked)}
                              />{' '}
                              leaf
                            </label>
                            <button type="submit" disabled={gapSaving}>
                              Add
                            </button>
                            <button type="button" className="quiet" onClick={() => setOpenGapKey(null)}>
                              Cancel
                            </button>
                          </form>
                        ) : (
                          <button
                            type="button"
                            className="add-gap-trigger"
                            aria-label="Add account here"
                            onClick={() => openGapForm(i)}
                          >
                            +
                          </button>
                        )}
                      </td>
                    </tr>
                  ) : (
                    <tr
                      key={row.key}
                      className={
                        `acct-row${row.account.is_active ? '' : ' inactive'}` +
                        (!row.account.is_postable && collapsed.has(row.account.id) ? ' collapsed' : '')
                      }
                      data-postable={row.account.is_postable ? '1' : '0'}
                      hidden={hiddenById.get(row.account.id)}
                    >
                      <td className="mono dim">{row.account.code}</td>
                      <td
                        className={`acct-name depth-${Math.min(row.account.depth, 6)}`}
                        onClick={() => toggleCollapse(row.account)}
                      >
                        <span className="tree-toggle" />
                        {row.account.name}
                      </td>
                      <td className="dim">{TYPE_LABELS[row.account.account_type]}</td>
                      <td className="dim">{row.account.is_postable ? 'leaf' : 'summary'}</td>
                      <td className="dim">{row.account.is_cashflow ? 'cash' : ''}</td>
                      <td>
                        <button type="button" className="quiet" onClick={() => toggleActive(row.account)}>
                          {row.account.is_active ? 'Archive' : 'Unarchive'}
                        </button>
                        <button type="button" className="quiet" onClick={() => toggleCashflow(row.account)}>
                          {row.account.is_cashflow ? 'Unmark cash' : 'Mark as cash'}
                        </button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          )}

          <div className="panel">
            <h2>New account</h2>
            <form className="grid-form" onSubmit={handleCreateAccount}>
              <label className="field">
                Code
                <input
                  type="text"
                  required
                  pattern="[0-9]{3,8}"
                  placeholder="e.g. 5510"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </label>
              <label className="field">
                Name
                <input
                  type="text"
                  required
                  placeholder="e.g. Streaming Services"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="field">
                Type
                <select value={accountType} onChange={(e) => setAccountType(e.target.value as AccountType)}>
                  {ACCOUNT_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {TYPE_LABELS[t]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Parent
                <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
                  <option value="">None (top level)</option>
                  {(accounts ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} · {a.path}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkline">
                <input type="checkbox" checked={isPostable} onChange={(e) => setIsPostable(e.target.checked)} />{' '}
                postable (leaf)
              </label>
              <label className="checkline">
                <input type="checkbox" checked={isCashflow} onChange={(e) => setIsCashflow(e.target.checked)} />{' '}
                counts as cash (Cash Flow)
              </label>
              <button type="submit" disabled={creating}>
                Create account
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  )
}
