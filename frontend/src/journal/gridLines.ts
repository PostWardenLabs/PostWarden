export interface GridLine {
  key: string
  account: string
  debit: string
  credit: string
  memo: string
}

// Split out of EntryGrid.tsx so that file exports only its default
// component — the identical `react(only-export-components)` Fast
// Refresh warning `confirmContext.ts` was already split out of
// `ConfirmDialog.tsx` to avoid, same fix here.
let nextKey = 0
export function makeBlankLine(): GridLine {
  nextKey += 1
  return { key: `line-${nextKey}`, account: '', debit: '', credit: '', memo: '' }
}

export function isLineUsed(line: GridLine): boolean {
  return line.account !== '' || line.debit.trim() !== '' || line.credit.trim() !== '' || line.memo.trim() !== ''
}

// Always exactly one blank row at the end, never trimming the row
// someone's still focused
// in (a fresh combobox search left mid-type, say). `focusedKey` is
// `NewEntryPanel.tsx`'s own last-focused-row tracking (see its
// `onFocusRow`), the same value Distribute needs — see its own comment
// there for why both need it.
export function ensureTrailingBlank(lines: GridLine[], focusedKey: string | null): GridLine[] {
  let ls = lines
  if (ls.length === 0 || isLineUsed(ls[ls.length - 1])) ls = [...ls, makeBlankLine()]
  while (
    ls.length > 2 &&
    !isLineUsed(ls[ls.length - 1]) &&
    !isLineUsed(ls[ls.length - 2]) &&
    ls[ls.length - 1].key !== focusedKey
  ) {
    ls = ls.slice(0, -1)
  }
  return ls
}
