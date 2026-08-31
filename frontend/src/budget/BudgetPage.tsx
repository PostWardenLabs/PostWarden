import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { Link, useSearchParams } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import { formatMoneyOrDash } from '../format/money'
import Combobox from '../widgets/Combobox'
import { useConfirm } from '../widgets/confirmContext'
import { useCollapsibleTree, type CollapsibleRow } from '../widgets/useCollapsibleTree'

// The Editable grid archetype's only instance (docs/ARCHITECTURE.md,
// "Component archetypes").
//
// GET /budget's own response is a plain `dict` (`modules/budget/
// router.py`), so openapi-fetch can only type it as `{[key: string]:
// unknown}` — same gap every other report page's own comment documents,
// cast through these local interfaces instead.
interface Quickfill {
  last_actual: string | number
  last_scenario: string | number
  avg3_actual: string | number
  avg3_scenario: string | number
}

// `id` is never optional here, unlike `TrialBalancePage.tsx`/
// `VariancePage.tsx`'s own `Row` — every row on this grid comes straight
// off `dim_accounts` (`repository.dim_accounts`), so there's no synthetic
// id-less row equivalent to Trial Balance's unclosed-earnings lines.
interface Row extends CollapsibleRow {
  id: number
  account_code: string
  account_name: string
  path?: string
  depth: number
  account_type: string
  actual: string | number
  budgeted: string | number
  variance: string | number
  pct_variance: string | null
  quickfill: Quickfill
}

interface Group {
  type: string
  label: string
  rows: Row[]
  sub_actual: string | number
  sub_budgeted: string | number
  sub_variance: string | number
  sub_pct_variance: string | null
}

interface BudgetResult {
  grouped: Group[]
  net_actual: string | number
  net_budgeted: string | number
  net_variance: string | number
  net_pct_variance: string | null
  scenario: string
  month: string
  month_options: string[]
  prev_month: string
  next_month: string
  pct_of_base: number
  month_start: string
  month_end: string
}

interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

function toNumber(v: string | number): number {
  return typeof v === 'number' ? v : parseFloat(v)
}

// A budgeted cell's own raw editable value — blank for a real zero, same
// as budget.html's own `'%.2f' % r.budgeted if r.budgeted else ''`, not
// `formatMoney()`/`formatMoneyOrDash()` (no thousands separator/currency
// symbol, and no dash either, on an input meant to be typed back into —
// a dash placeholder would have to be deleted before typing a real
// number over it, same reason EntryGrid.tsx's own debit/credit cells
// stay blank rather than switching to a dash for this feature too).
function rawAmount(v: number): string {
  return v ? v.toFixed(2) : ''
}

// Same two formulas as `domain.money.variance_amount`/`pct_variance`
// (backend) — duplicated here, not imported, because a leaf's own
// Budgeted figure has to recompute live, in the browser, as it's typed,
// with no round trip.
function varianceAmount(actual: number, budgeted: number, pctOfBase: boolean): number {
  return pctOfBase ? budgeted - actual : actual - budgeted
}

function pctVariance(actual: number, budgeted: number, pctOfBase: boolean): number | null {
  if (pctOfBase) {
    if (!actual) return null
    return Math.round(((budgeted - actual) / Math.abs(actual)) * 1000) / 10
  }
  if (!budgeted) return null
  return Math.round(((actual - budgeted) / Math.abs(budgeted)) * 1000) / 10
}

// Same "—" for nothing to divide by, colored-if-negative treatment as
// Income Statement's/Variance's own `var()` macro.
function pctText(pct: number | null) {
  if (pct === null) return <span className="dim">—</span>
  return <span className={pct < 0 ? 'neg' : undefined}>{pct.toFixed(1)}%</span>
}

interface GridComputation {
  budgetedById: Map<number, number>
  varianceById: Map<number, number>
  pctById: Map<number, number | null>
  typeBudgeted: Record<string, number>
  typeVariance: Record<string, number>
  typePct: Record<string, number | null>
  netBudgeted: number
  netVariance: number
  netPct: number | null
}

// One pass, bottom-up: a leaf's Budgeted is whatever's currently typed
// (`edits`, keyed by account id) or, untouched, the server's own figure;
// a summary account's Budgeted is always the sum of its own children,
// live. Actual never recomputes — every row already carries its own
// static, server-rendered figure (this module's own docstring on
// `budget_grid`), so only Budgeted (and anything derived from it) ever
// changes here.
function computeGrid(result: BudgetResult, edits: Record<number, string>, pctOfBase: boolean): GridComputation {
  const allRows = result.grouped.flatMap((g) => g.rows)
  const byId = new Map<number, Row>()
  for (const r of allRows) byId.set(r.id, r)
  const childrenOf = new Map<number, Row[]>()
  for (const r of allRows) {
    if (r.parent_id != null && byId.has(r.parent_id)) {
      const siblings = childrenOf.get(r.parent_id) ?? []
      siblings.push(r)
      childrenOf.set(r.parent_id, siblings)
    }
  }

  const budgetedById = new Map<number, number>()
  function budgetedOf(r: Row): number {
    const cached = budgetedById.get(r.id)
    if (cached !== undefined) return cached
    let b: number
    if (!r.has_children) {
      const edited = edits[r.id]
      b = edited !== undefined ? parseFloat(edited) || 0 : toNumber(r.budgeted)
    } else {
      b = (childrenOf.get(r.id) ?? []).reduce((sum, child) => sum + budgetedOf(child), 0)
    }
    budgetedById.set(r.id, b)
    return b
  }

  const varianceById = new Map<number, number>()
  const pctById = new Map<number, number | null>()
  for (const r of allRows) {
    const b = budgetedOf(r)
    const a = toNumber(r.actual)
    varianceById.set(r.id, varianceAmount(a, b, pctOfBase))
    pctById.set(r.id, pctVariance(a, b, pctOfBase))
  }

  const typeBudgeted: Record<string, number> = {}
  const typeVariance: Record<string, number> = {}
  const typePct: Record<string, number | null> = {}
  for (const g of result.grouped) {
    const roots = g.rows.filter((r) => r.parent_id == null || !byId.has(r.parent_id))
    const b = roots.reduce((sum, r) => sum + budgetedOf(r), 0)
    const a = toNumber(g.sub_actual)
    typeBudgeted[g.type] = b
    typeVariance[g.type] = varianceAmount(a, b, pctOfBase)
    typePct[g.type] = pctVariance(a, b, pctOfBase)
  }

  const netBudgeted = (typeBudgeted.income ?? 0) - (typeBudgeted.expense ?? 0)
  const netActual = toNumber(result.net_actual)
  return {
    budgetedById,
    varianceById,
    pctById,
    typeBudgeted,
    typeVariance,
    typePct,
    netBudgeted,
    netVariance: varianceAmount(netActual, netBudgeted, pctOfBase),
    netPct: pctVariance(netActual, netBudgeted, pctOfBase),
  }
}

interface MenuOption {
  label: string
  onSelect: () => void
}

interface MenuState {
  key: string
  anchor: HTMLElement
  top: number
  left?: number
  right?: number
  options: MenuOption[]
}

export default function BudgetPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scenarios = useScenarios()
  const confirm = useConfirm()
  const [result, setResult] = useState<BudgetResult | null>(null)
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [saveStatus, setSaveStatus] = useState('')
  const [menu, setMenu] = useState<MenuState | null>(null)
  const menuPanelRef = useRef<HTMLDivElement>(null)
  // What the server last confirmed for a given leaf's own cell — reset
  // whenever a fresh `result` arrives (a real scenario/month/flip
  // change), starting over from whatever the server just sent. A ref,
  // not state: comparing against it on blur shouldn't itself trigger a
  // re-render.
  const savedRef = useRef<Record<number, string>>({})

  // Budget Grid is income-statement-only by definition
  // (`fn_budget_line_guard`) — filtered before ever building the picker;
  // this is this page's own filter, since no other screen needs an
  // income-statement-only scenario list.
  const isoScenarios = useMemo(() => (scenarios ?? []).filter((s) => s.income_statement_only), [scenarios])
  const scenario = searchParams.get('scenario') || isoScenarios[0]?.code || ''
  const urlMonth = searchParams.get('month') || ''
  const displayMonth = result ? result.month.slice(0, 7) : urlMonth
  const pctOfBase = searchParams.get('pct_of_base') === '1'

  useEffect(() => {
    let cancelled = false
    client
      .GET('/budget', { params: { query: { scenario, month: urlMonth, pct_of_base: pctOfBase ? 1 : 0 } } })
      .then(({ data }) => {
        if (cancelled || !data) return
        const budgetResult = data as unknown as BudgetResult
        // Reseeds every leaf's own editable value (and what counts as
        // "already saved," for the blur-triggered save below) from
        // whatever the server just sent — right alongside `setResult`
        // itself, in the same fetch this is the natural response to, not
        // a second effect merely reacting to `result` having changed
        // (which would fire on every render for no external reason and
        // start a cascading render oxlint's own `set-state-in-effect`
        // rule flags). Never runs as a side effect of typing or of an
        // individual cell's own save, neither of which ever calls
        // `setResult`.
        const map: Record<number, string> = {}
        for (const g of budgetResult.grouped) {
          for (const r of g.rows) {
            if (!r.has_children) map[r.id] = rawAmount(toNumber(r.budgeted))
          }
        }
        savedRef.current = map
        setResult(budgetResult)
        setEdits(map)
      })
    return () => {
      cancelled = true
    }
  }, [scenario, urlMonth, pctOfBase])

  const grid = useMemo(() => (result ? computeGrid(result, edits, pctOfBase) : null), [result, edits, pctOfBase])
  const collapseKey = `postwarden-budget-collapsed-${scenario}`
  const allRows = result ? result.grouped.flatMap((g) => g.rows) : []
  const tree = useCollapsibleTree(collapseKey, allRows)

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  function pageParams(overrides: Record<string, string>): string {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(overrides)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    return next.toString()
  }

  async function saveCell(row: Row, rawValue: string) {
    const trimmed = rawValue.trim()
    if (trimmed === (savedRef.current[row.id] ?? '')) return
    if (!result) return
    const scenarioId = scenarios?.find((s) => s.code === scenario)?.id
    if (scenarioId === undefined) return
    setSaveStatus('Saving…')
    const { error: err } = await client.POST('/budget/cell', {
      body: { scenario_id: scenarioId, account: row.account_code, period_month: result.month_start, amount: trimmed },
    })
    if (err) {
      setSaveStatus(errorDetail(err, 'Could not save'))
      return
    }
    savedRef.current[row.id] = trimmed
    setSaveStatus('Saved')
  }

  // Quick fill (per-cell chevron and page-level "Set all values" both
  // reuse this) — recompute + save run back to back, exactly what typing
  // into a cell and blurring it already does, just triggered by a menu
  // pick instead of a keystroke.
  async function fillAndSave(row: Row, value: number) {
    const str = value.toFixed(2)
    setEdits((prev) => ({ ...prev, [row.id]: str }))
    await saveCell(row, str)
  }

  function toggleMenu(key: string, anchorEl: HTMLElement, align: 'below-right' | 'below-left', options: MenuOption[]) {
    setMenu((prev) => {
      if (prev?.key === key) return null
      const rect = anchorEl.getBoundingClientRect()
      return align === 'below-left'
        ? { key, anchor: anchorEl, top: rect.bottom + 2, left: rect.left, options }
        : { key, anchor: anchorEl, top: rect.bottom + 2, right: window.innerWidth - rect.right, options }
    })
  }

  // Closes on an outside click, Escape, or scroll. The anchor itself is
  // excluded from the "outside click" check so a second click on the
  // same chevron toggles the menu closed (via toggleMenu's own
  // prev.key === key branch) instead of this effect closing it first and
  // the click handler immediately reopening it.
  useEffect(() => {
    if (!menu) return
    function onMouseDown(e: globalThis.MouseEvent) {
      const target = e.target as Node
      if (menu!.anchor.contains(target) || menuPanelRef.current?.contains(target)) return
      setMenu(null)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenu(null)
    }
    function onScroll() {
      setMenu(null)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [menu])

  function openCellMenu(e: MouseEvent<HTMLButtonElement>, row: Row) {
    toggleMenu(`cell-${row.id}`, e.currentTarget, 'below-right', [
      { label: 'Set to ACTUAL value of last month', onSelect: () => fillAndSave(row, toNumber(row.quickfill.last_actual)) },
      {
        label: `Set to ${scenario} value of last month`,
        onSelect: () => fillAndSave(row, toNumber(row.quickfill.last_scenario)),
      },
      { label: 'Set to 3 month average of ACTUAL', onSelect: () => fillAndSave(row, toNumber(row.quickfill.avg3_actual)) },
      {
        label: `Set to 3 month average of ${scenario}`,
        onSelect: () => fillAndSave(row, toNumber(row.quickfill.avg3_scenario)),
      },
    ])
  }

  async function setAll(field: keyof Quickfill, label: string) {
    if (!result) return
    const ok = await confirm(`Overwrite every budgeted value this month with ${label}? This can't be undone.`)
    if (!ok) return
    const leaves = result.grouped.flatMap((g) => g.rows).filter((r) => !r.has_children)
    await Promise.all(leaves.map((row) => fillAndSave(row, toNumber(row.quickfill[field]))))
  }

  function openSetAllMenu(e: MouseEvent<HTMLButtonElement>) {
    toggleMenu('set-all', e.currentTarget, 'below-left', [
      {
        label: 'SET ALL VALUES to ACTUAL values for last month',
        onSelect: () => setAll('last_actual', 'their ACTUAL value for last month'),
      },
      {
        label: `SET ALL VALUES to ${scenario} values for last month`,
        onSelect: () => setAll('last_scenario', `${scenario}'s own value for last month`),
      },
      {
        label: 'SET ALL VALUES to 3 month average of their ACTUAL values',
        onSelect: () => setAll('avg3_actual', 'the 3 month average of their ACTUAL values'),
      },
      {
        label: `SET ALL VALUES to 3 month average of their ${scenario} values`,
        onSelect: () => setAll('avg3_scenario', `the 3 month average of their ${scenario} values`),
      },
    ])
  }

  if (scenarios !== null && isoScenarios.length === 0) {
    return (
      <>
        <div className="page-head" />
        <p className="dim">
          No income-statement-only scenarios yet. Create one from <Link to="/app/scenarios">Scenarios</Link> — check
          "income statement only" when you do.
        </p>
      </>
    )
  }

  const scenExists = isoScenarios.some((s) => s.code === scenario)

  return (
    <>
      <div className="page-head">
        <Link to="/app/help#budget-grid" className="help-icon" aria-label="How this works" title="How this works">
          ?
        </Link>
      </div>

      <div className="bar" style={{ justifyContent: 'space-between' }}>
        <span className="bar" style={{ marginBottom: 0 }}>
          <label className="field">
            Scenario
            <Combobox
              options={isoScenarios.map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
              value={scenario}
              onChange={(v) => setParam('scenario', v)}
            />
          </label>
          <label className="field">
            Month
            <Combobox
              options={(result?.month_options ?? []).map((m) => ({ value: m, label: m }))}
              value={displayMonth}
              onChange={(v) => setParam('month', v)}
            />
          </label>
        </span>
        {result && (
          <span className="bar" style={{ marginBottom: 0 }}>
            <Link className="quiet-link" to={`?${pageParams({ month: result.prev_month.slice(0, 7) })}`}>
              &larr; {result.prev_month.slice(0, 7)}
            </Link>
            <Link className="quiet-link" to={`?${pageParams({ month: result.next_month.slice(0, 7) })}`}>
              {result.next_month.slice(0, 7)} &rarr;
            </Link>
          </span>
        )}
      </div>

      <p className="bar" style={{ alignItems: 'center' }}>
        <label
          className="checkline"
          title="Default: Actual − Budgeted, as a % of Budgeted. Checked: Budgeted − Actual, as a % of Actual."
        >
          <input
            type="checkbox"
            checked={pctOfBase}
            onChange={(e) => setParam('pct_of_base', e.target.checked ? '1' : '')}
          />
          Flip variance direction
        </label>
      </p>

      {result === null ? (
        <p>Loading…</p>
      ) : !scenExists ? (
        <p className="dim">
          Scenario <span className="mono">{scenario}</span> not found or isn't income-statement-only.
        </p>
      ) : result.grouped.length === 0 ? (
        <p className="dim">No activity in this scenario yet.</p>
      ) : (
        <div className="report-frame">
          {/* The page-level bulk option — applies the same
              four quick-fill sources as a single cell's own chevron menu
              to every leaf cell at once, behind a real confirm since it
              overwrites whatever's already typed everywhere on the grid.
              No Export CSV/XLSX here — `modules/budget/router.py` has no
              `.csv`/`.xlsx` sibling, unlike `modules/reports/`/
              `modules/entries/`. Deliberate, decided on the record: the
              grid is a working view of the Variance report, which has
              the export — see docs/ARCHITECTURE.md's "Archetype
              conventions". */}
          <p className="bar" style={{ alignItems: 'center' }}>
            <button
              type="button"
              className="quiet"
              style={{ display: 'inline-flex', alignItems: 'center' }}
              onClick={openSetAllMenu}
            >
              Set all values<span className="chevron chevron-down" style={{ marginLeft: '0.4rem' }} />
            </button>
          </p>

          <table className="ledger report-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num money money-first">Actual</th>
                <th className="num money">Variance</th>
                <th className="num">% variance</th>
                <th className="num money">Budgeted</th>
              </tr>
            </thead>
            <tbody>
              {result.grouped.map((g) => (
                <GroupRows
                  key={g.type}
                  group={g}
                  tree={tree}
                  grid={grid!}
                  edits={edits}
                  onCellChange={(row, value) => setEdits((prev) => ({ ...prev, [row.id]: value }))}
                  onCellBlur={(row) => saveCell(row, edits[row.id] ?? '')}
                  onCellMenu={openCellMenu}
                />
              ))}
              <tr className="grand">
                <td></td>
                <td>Net (Income &minus; Expenses)</td>
                <td className="num money money-first">{formatMoneyOrDash(result.net_actual)}</td>
                <td className={`num money ${grid!.netVariance < 0 ? 'neg' : ''}`}>{formatMoneyOrDash(grid!.netVariance)}</td>
                <td className="num">{pctText(grid!.netPct)}</td>
                <td className="num money budgeted-cell">{formatMoneyOrDash(grid!.netBudgeted)}</td>
              </tr>
            </tbody>
          </table>
          <p className="dim small" aria-live="polite">
            {saveStatus}
          </p>
        </div>
      )}

      {menu &&
        createPortal(
          <div
            ref={menuPanelRef}
            className="combobox-panel quickfill-menu"
            style={{ top: menu.top, left: menu.left, right: menu.right }}
          >
            {menu.options.map((opt) => (
              <div
                key={opt.label}
                className="combobox-option"
                onMouseDown={(e) => {
                  e.preventDefault() // don't steal focus from the input before onSelect() reads/writes it
                  opt.onSelect()
                  setMenu(null)
                }}
              >
                {opt.label}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  )
}

function GroupRows({
  group,
  tree,
  grid,
  edits,
  onCellChange,
  onCellBlur,
  onCellMenu,
}: {
  group: Group
  tree: ReturnType<typeof useCollapsibleTree>
  grid: GridComputation
  edits: Record<number, string>
  onCellChange: (row: Row, value: string) => void
  onCellBlur: (row: Row) => void
  onCellMenu: (e: MouseEvent<HTMLButtonElement>, row: Row) => void
}) {
  const typeBudgeted = grid.typeBudgeted[group.type] ?? 0
  const typeVariance = grid.typeVariance[group.type] ?? 0
  const typePct = grid.typePct[group.type] ?? null
  return (
    <>
      <tr className="type-head">
        <td colSpan={6}>{group.label}</td>
      </tr>
      {group.rows.map((r) =>
        tree.isHidden(r) ? null : (
          <tr
            key={r.id}
            className={r.has_children && tree.isCollapsed(r.id) ? 'collapsed' : undefined}
            data-has-children={r.has_children ? '1' : '0'}
          >
            <td className="mono dim">{r.account_code}</td>
            <td className={`acct-name depth-${Math.min(r.depth, 6)}`} onClick={() => r.has_children && tree.toggle(r.id)}>
              <span className="tree-toggle" />
              {r.account_name} {r.path && <span className="dim small">{r.path}</span>}
            </td>
            <td className="num money money-first">{formatMoneyOrDash(r.actual)}</td>
            <td className={`num money ${(grid.varianceById.get(r.id) ?? 0) < 0 ? 'neg' : ''}`}>
              {formatMoneyOrDash(grid.varianceById.get(r.id) ?? 0)}
            </td>
            <td className="num pct-variance-cell">{pctText(grid.pctById.get(r.id) ?? null)}</td>
            {r.has_children ? (
              <td className="num money budgeted-cell">{formatMoneyOrDash(grid.budgetedById.get(r.id) ?? 0)}</td>
            ) : (
              <td className="num money budget-cell-wrap">
                <input
                  className="amount budget-cell"
                  inputMode="decimal"
                  value={edits[r.id] ?? ''}
                  onChange={(e) => onCellChange(r, e.target.value)}
                  onBlur={() => onCellBlur(r)}
                />
                {/* tabIndex={-1}: a bonus shortcut, not the primary way to
                    enter a value — every cell staying keyboard-typeable is
                    what actually matters. */}
                <button
                  type="button"
                  className="quickfill-toggle"
                  aria-label="Quick fill options"
                  tabIndex={-1}
                  onClick={(e) => onCellMenu(e, r)}
                >
                  <span className="chevron chevron-down" />
                </button>
              </td>
            )}
          </tr>
        ),
      )}
      <tr className="subtotal">
        <td></td>
        <td>{group.label} subtotal</td>
        <td className="num money money-first">{formatMoneyOrDash(group.sub_actual)}</td>
        <td className={`num money ${typeVariance < 0 ? 'neg' : ''}`}>{formatMoneyOrDash(typeVariance)}</td>
        <td className="num pct-variance-cell">{pctText(typePct)}</td>
        <td className="num money budgeted-cell">{formatMoneyOrDash(typeBudgeted)}</td>
      </tr>
    </>
  )
}
