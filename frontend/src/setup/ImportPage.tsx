import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import ImportMappedPanel from './ImportMappedPanel'
import ImportPlainPanel from './ImportPlainPanel'

// The Import screen's own container: a page-head, a two-way tab bar,
// and the "Recent imports" table shared by both tabs, since both
// importers ultimately funnel through the same `stage_import_groups`
// (modules/imports/service.py's own docstring) and land in the same
// `import_batches` table — there's only ever one real history to show,
// regardless of which tab produced a given row.
//
// This page used to be two: a plain `ImportPage.tsx` with the whole of
// what's now `ImportPlainPanel.tsx`, reachable from the sidebar, and a
// separate `ImportMappedPage.tsx` (now `ImportMappedPanel.tsx`) at
// `/app/import/mapped`, reachable only via a text link buried in the
// first page's copy — flagged in BACKLOG.md as "weird," since a user
// with a single-entry export had to already know the second importer
// existed. One nav entry, one URL, two tabs fixes that: whichever
// shape a file turns out to be, the other importer is one click away,
// not a hunt through prose.
//
// Each tab is unmounted while inactive (a plain `mode === 'x' && <.../>`
// below, not both panels kept mounted and hidden via CSS) — switching
// tabs mid-way through the mapped importer's upload/review flow loses
// that in-progress state, same as navigating away from it used to.
// Accepted trade-off: two file inputs with the same `id` can't both
// exist in the DOM at once anyway (FileField.tsx's `id` prop), and
// losing an in-progress upload on a deliberate tab switch is a
// reasonable expectation, not a surprise.
type Mode = 'plain' | 'mapped'

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
  const [mode, setMode] = useState<Mode>('plain')
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

      <div className="bar" role="tablist" aria-label="Import method">
        <button type="button" role="tab" aria-selected={mode === 'plain'}
                className={mode === 'plain' ? '' : 'quiet'} onClick={() => setMode('plain')}>
          CSV import
        </button>
        <button type="button" role="tab" aria-selected={mode === 'mapped'}
                className={mode === 'mapped' ? '' : 'quiet'} onClick={() => setMode('mapped')}>
          Import with rules
        </button>
      </div>

      {mode === 'plain' && <ImportPlainPanel onStaged={reload} />}
      {mode === 'mapped' && <ImportMappedPanel onStaged={reload} />}

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
