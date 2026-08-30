import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { useAccountLevels } from '../api/useAccountLevels'
import client from '../api/client'

// Ported from app/templates/scenarios.html (Phase 4.2) — no vanilla-JS
// counterpart beyond the inline `<script>` toggling the two fields below
// (ported as a plain `income statement only` boolean gating the render,
// not a DOM `hidden` toggle). Structurally unlike Payees/Tags: no
// Select/Merge bar, no inline rename, no Archive/Delete — legacy's own
// table has exactly one per-row action (Lock/Unlock), and the "add" UI
// is a permanent `<div class="panel">` form, not a collapsible `<details
// class="entry-new">` (scenarios.html never wraps it in one, unlike
// payees.html/tags.html), so this page doesn't reuse `useSelectMode.ts`/
// `MergeDialog.tsx` at all — nothing here is a set-based bulk operation.
//
// `useAccountLevels()` (`api/useAccountLevels.ts`) is its second caller,
// exactly as that hook's own Phase 3.4 comment predicted — `usePostable
// Accounts.ts` was the first.
type ScenarioType = 'budget' | 'forecast' | 'what_if'
const SCENARIO_TYPES: ScenarioType[] = ['budget', 'forecast', 'what_if']

interface ScenarioRow {
  id: number
  code: string
  name: string
  scenario_type: string
  is_staging: boolean
  is_locked: boolean
  income_statement_only: boolean
  enforce_balance: boolean
  base_level_name: string | null
  entry_count: number
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

function kindLabel(s: ScenarioRow): string {
  if (s.income_statement_only) return 'income statement only'
  return s.is_staging ? 'staging (auto-populated only)' : 'full ledger'
}

function balanceRuleLabel(s: ScenarioRow): string {
  if (s.income_statement_only) return '—'
  return s.enforce_balance ? 'must balance' : 'single-sided OK'
}

function baseLevelLabel(s: ScenarioRow): string {
  if (s.income_statement_only) return '—'
  return s.base_level_name || '— leaves only —'
}

export default function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioRow[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const levels = useAccountLevels()

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [scenarioType, setScenarioType] = useState<ScenarioType>('budget')
  const [incomeStatementOnly, setIncomeStatementOnly] = useState(false)
  const [enforceBalance, setEnforceBalance] = useState(false)
  const [baseLevelId, setBaseLevelId] = useState('')
  const [notes, setNotes] = useState('')
  const [creating, setCreating] = useState(false)

  const reload = useCallback(async () => {
    const { data } = await client.GET('/scenarios')
    if (data) setScenarios(data as unknown as ScenarioRow[])
  }, [])

  useEffect(() => {
    let cancelled = false
    client.GET('/scenarios').then(({ data }) => {
      if (!cancelled && data) setScenarios(data as unknown as ScenarioRow[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    const { data, error } = await client.POST('/scenarios', {
      body: {
        code,
        name,
        scenario_type: scenarioType,
        enforce_balance: incomeStatementOnly ? false : enforceBalance,
        income_statement_only: incomeStatementOnly,
        base_level_id: incomeStatementOnly || !baseLevelId ? null : Number(baseLevelId),
        notes: notes || null,
      },
    })
    setCreating(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not create scenario') })
      return
    }
    setFlash({ ok: `Scenario “${(data as unknown as { code: string }).code}” created` })
    setCode('')
    setName('')
    setScenarioType('budget')
    setIncomeStatementOnly(false)
    setEnforceBalance(false)
    setBaseLevelId('')
    setNotes('')
    await reload()
  }

  async function toggleLock(s: ScenarioRow) {
    const { error } = await client.POST('/scenarios/{scenario_id}/toggle-lock', {
      params: { path: { scenario_id: s.id } },
    })
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not update scenario') })
      return
    }
    setFlash({ ok: s.is_locked ? `“${s.name}” unlocked` : `“${s.name}” locked` })
    await reload()
  }

  if (scenarios === null || levels === null) return <p>Loading…</p>

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#scenarios" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <table className="ledger">
        <thead>
          <tr>
            <th>Code</th>
            <th>Name</th>
            <th>Type</th>
            <th>Kind</th>
            <th>Balance rule</th>
            <th>Base level</th>
            <th className="num">Entries</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {scenarios.map((s) => (
            <tr key={s.id}>
              <td className="mono">{s.code}</td>
              <td>{s.name}</td>
              <td className="dim">{s.scenario_type}</td>
              <td className="dim">{kindLabel(s)}</td>
              <td className="dim">{balanceRuleLabel(s)}</td>
              <td className="dim">{baseLevelLabel(s)}</td>
              <td className="num mono">{s.entry_count}</td>
              <td>
                {s.is_locked ? (
                  <span className="badge rev">locked</span>
                ) : (
                  <span className="badge">open</span>
                )}
              </td>
              <td>
                <button type="button" className="quiet" onClick={() => toggleLock(s)}>
                  {s.is_locked ? 'Unlock' : 'Lock'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="panel">
        <h2>New scenario</h2>
        <form className="grid-form" onSubmit={handleCreate}>
          <label className="field">
            Code
            <input
              type="text"
              required
              pattern="[A-Za-z0-9_]{2,24}"
              placeholder="e.g. FCST_2026_09"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          <label className="field">
            Name
            <input
              type="text"
              required
              placeholder="e.g. September forecast"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="field">
            Type
            <select value={scenarioType} onChange={(e) => setScenarioType(e.target.value as ScenarioType)}>
              {SCENARIO_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="checkline">
            <input
              type="checkbox"
              checked={incomeStatementOnly}
              onChange={(e) => setIncomeStatementOnly(e.target.checked)}
            />
            income statement only (budget grid, no journal entries)
          </label>
          {/* Hidden once income-statement-only is checked — an
              income-statement-only scenario has no journal entries at
              all, so "require balanced entries" and "base level" (both
              about how entries post) don't apply, same reasoning
              scenarios.html's own inline `<script>` gives. */}
          {!incomeStatementOnly && (
            <label className="checkline">
              <input
                type="checkbox"
                checked={enforceBalance}
                onChange={(e) => setEnforceBalance(e.target.checked)}
              />
              require balanced entries
            </label>
          )}
          {!incomeStatementOnly && (
            <label className="field">
              Base level
              <select value={baseLevelId} onChange={(e) => setBaseLevelId(e.target.value)}>
                <option value="">Leaves only (default)</option>
                {levels.map((lv) => (
                  <option key={lv.id} value={lv.id}>
                    {lv.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field" style={{ gridColumn: '1 / -1' }}>
            Notes
            <input
              type="text"
              placeholder="Optional"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <button type="submit" disabled={creating}>
            Create scenario
          </button>
        </form>
      </div>
    </>
  )
}
