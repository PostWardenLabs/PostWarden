import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import ImportMappedPanel from './ImportMappedPanel'

// The Import screen's own container: a page-head, the import wizard,
// and the "Recent imports" table below it.
//
// This page used to mount two separate importers behind a tab bar — a
// fixed-column "CSV import" panel (`ImportPlainPanel.tsx`) and a
// column-mapping "Import with rules" wizard (`ImportMappedPanel.tsx`) —
// because the wizard couldn't yet express the fixed importer's own
// grouped/Debit-Credit/direct-code shape. IMPORT_WIZARD.md §7 Phase 4
// made that shape (and every other combination) a wizard setting
// instead of a separate code path, so the two importers merged into
// one: `ImportMappedPanel.tsx` alone, no tab bar, no mode to choose.
// `ImportPlainPanel.tsx` and its `POST /import` route are deleted
// outright (Phase 4 item 5) rather than kept as a shortcut, since the
// wizard's own default shape (grouped, Debit/Credit, direct codes)
// already reproduces the old fixed importer's zero-friction path for a
// file shaped that way — see `ImportMappedPanel.tsx`'s own Shape panel.
interface RecentBatch {
  id: number
  filename: string
  row_count: number
  target_scenario_code: string
  imported_by: string | null
  created_at: string
}

// `created_at` is a real timestamp (TIMESTAMPTZ, `.isoformat()` over the
// wire), not a plain date — `format/date.ts`'s own `formatDate` only
// ever handles a bare `YYYY-MM-DD` (its own regex rejects anything
// else), so this is a small local formatter instead, rendered in the
// visitor's own local timezone — fine for what's purely an informational
// "when," not ledger data itself.
function formatBatchTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ImportPage() {
  const [recent, setRecent] = useState<RecentBatch[] | null>(null)

  function reload() {
    client.GET('/import').then(({ data }) => {
      if (data) setRecent((data as unknown as { recent_batches: RecentBatch[] }).recent_batches)
    })
  }

  // Separate from `reload()` above (called again after either tab
  // stages a batch) so the initial fetch can guard against setting
  // state on an unmounted component — same `cancelled` shape
  // `AccountLevelsPage.tsx`/`AccountsPage.tsx` already use for the
  // identical local-fetch-plus-reload pattern.
  useEffect(() => {
    let cancelled = false
    client.GET('/import').then(({ data }) => {
      if (!cancelled && data) setRecent((data as unknown as { recent_batches: RecentBatch[] }).recent_batches)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          Imported entries land in <Link className="quiet-link" to="/app/staging">Staging</Link> for review,
          same as a scheduled entry.
        </p>
        <Link to="/app/help#import" className="help-icon" aria-label="How this works" title="How this works">?</Link>
      </div>

      <ImportMappedPanel onStaged={reload} />

      {!!recent?.length && (
        <>
          <h2 style={{ marginTop: '2rem' }}>Recent imports</h2>
          <table className="ledger">
            <thead>
              <tr>
                <th>File</th><th>Target</th><th className="num">Entries</th><th>Imported by</th><th>When</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((b) => (
                <tr key={b.id}>
                  <td>{b.filename}</td>
                  <td className="mono dim">{b.target_scenario_code}</td>
                  <td className="num mono">{b.row_count}</td>
                  <td className="dim">{b.imported_by || '—'}</td>
                  <td className="dim">{formatBatchTime(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  )
}
