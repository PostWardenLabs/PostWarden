import { createContext, useContext } from 'react'

export interface ConfirmOptions {
  okLabel?: string
  cancelLabel?: string
  // Styles OK in --red (Delete/Reject — data actually gone); leave off
  // for a normal, reversible-enough action (Reverse an entry, Approve a
  // staged one) where red would overstate the risk.
  danger?: boolean
}

export type ConfirmFn = (message: string, opts?: ConfirmOptions) => Promise<boolean>

// Split out of ConfirmDialog.tsx so that file exports only components —
// oxlint's react(only-export-components) flags a mix of components and
// plain values/hooks in one file as a Fast Refresh hazard.
export const ConfirmContext = createContext<ConfirmFn | null>(null)

// Same true/false Promise shape as the native confirm() it replaces,
// just asynchronous — awaiting a click instead of blocking the whole
// page. See ConfirmDialog.tsx's own file comment for the full writeup.
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirm() must be used inside <ConfirmProvider>')
  return ctx
}
