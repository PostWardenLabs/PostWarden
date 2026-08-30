import { type RefObject } from 'react'

import Combobox, { type ComboboxOption } from '../widgets/Combobox'
import type { GridLine } from './gridLines'

type Field = 'account' | 'debit' | 'credit' | 'memo'

interface EntryGridProps {
  lines: GridLine[]
  accounts: ComboboxOption[]
  updateLine: (key: string, field: Field, value: string) => void
  tableRef: RefObject<HTMLTableElement | null>
  onFocusRow: (key: string) => void
}

// Ported from entries.html's `table.ledger.entry-grid` + app.js's row-
// level mechanics (Phase 3.4). Purely presentational plus keyboard
// navigation — `updateLine` (owned by `NewEntryPanel.tsx`) is where the
// debit/credit exclusivity and `ensureTrailingBlank` calls actually
// happen, same "grid renders, parent owns the entry" split
// `TrialBalancePage.tsx`'s own `GroupRows` already used for a report
// table.
//
// Keyboard nav (Enter/Shift+Enter move vertically, same column) is a
// real DOM query over the rendered table, not a ref registry — the same
// blend of React state and direct `.focus()` calls `DatePicker.tsx`
// already uses for its own roving-tabindex grid, for the identical
// reason: this is genuinely how app.js itself worked (`columns()`
// re-queries the DOM on every keypress), and a query is simpler than
// threading a per-cell ref map through a table that grows and shrinks
// rows on every keystroke.
export default function EntryGrid({ lines, accounts, updateLine, tableRef, onFocusRow }: EntryGridProps) {
  return (
    <table className="ledger entry-grid" id="lines" ref={tableRef}>
      <thead>
        <tr>
          <th className="col-account">Account</th>
          <th className="num col-amount money money-first">Debit</th>
          <th className="num col-amount money">Credit</th>
          <th>Memo</th>
        </tr>
      </thead>
      <tbody
        onFocus={(e) => {
          const tr = (e.target as HTMLElement).closest('tr[data-row-key]') as HTMLElement | null
          if (tr?.dataset.rowKey) onFocusRow(tr.dataset.rowKey)
        }}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || e.altKey || e.ctrlKey || e.metaKey) return
          const td = (e.target as HTMLElement).closest('td[data-col]') as HTMLElement | null
          const table = tableRef.current
          if (!td || !table) return
          const col = td.dataset.col
          const tr = td.closest('tr[data-row-key]') as HTMLElement | null
          if (!tr) return
          const rowEls = Array.from(table.querySelectorAll('tbody tr[data-row-key]'))
          const nextTr = rowEls[rowEls.indexOf(tr) + (e.shiftKey ? -1 : 1)] as HTMLElement | undefined
          if (!nextTr) return // top/bottom row for this column — nothing further to move to
          e.preventDefault()
          const nextField = nextTr.querySelector(
            `td[data-col="${col}"] .combobox-input, td[data-col="${col}"] input`,
          ) as HTMLElement | null
          nextField?.focus()
        }}
      >
        {lines.map((line) => (
          <tr key={line.key} data-row-key={line.key}>
            <td className="col-account" data-col="account">
              <Combobox options={accounts} value={line.account} onChange={(v) => updateLine(line.key, 'account', v)} />
            </td>
            <td className="col-amount money money-first" data-col="debit">
              <input
                className="amount"
                inputMode="decimal"
                value={line.debit}
                onChange={(e) => updateLine(line.key, 'debit', e.target.value)}
              />
            </td>
            <td className="col-amount money" data-col="credit">
              <input
                className="amount"
                inputMode="decimal"
                value={line.credit}
                onChange={(e) => updateLine(line.key, 'credit', e.target.value)}
              />
            </td>
            <td data-col="memo">
              <input value={line.memo} onChange={(e) => updateLine(line.key, 'memo', e.target.value)} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
