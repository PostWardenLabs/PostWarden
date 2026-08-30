import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import Combobox from '../widgets/Combobox'
import FileField from '../widgets/FileField'

// Ported from app/templates/import.html (Phase 4.7) — the plain
// double-entry CSV importer. Backend already fully built (`modules/
// imports/`, Phase 1.8/1.14); this screen is frontend-only, same as
// every Phase 4 screen except this phase's own Dashboard.
//
// `errorDetail`/`ErrorBody` — same local cast-from-`unknown` shape every
// write-route screen in this rebuild carries (`PayeesPage.tsx` and
// onward), since FastAPI's plain `HTTPException(400, detail=...)` isn't
// typed any more specifically than that in the generated client.
interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// `IMPORT_MAX_ERRORS_SHOWN` — mirrors `modules/imports/service.py`'s own
// constant of the same value (20). The backend's success response
// returns every row error, untruncated (`import_csv`'s own `errors` is
// the full list); legacy's own truncate-and-append-"...and N more" step
// happened in the route handler assembling `err_msg`, which has no
// equivalent here (`service.import_csv` just returns data, it doesn't
// format a message) — so this screen does that formatting instead,
// identical logic to Import-with-rule's own review step, which needs
// the same truncation for the same reason and forks it rather than
// sharing a one-off helper for two callers.
const IMPORT_MAX_ERRORS_SHOWN = 20

function skippedRowsMessage(errors: string[]): string {
  const shown = errors.slice(0, IMPORT_MAX_ERRORS_SHOWN)
  if (errors.length > shown.length) shown.push(`...and ${errors.length - shown.length} more`)
  return `${errors.length} row(s) skipped: ${shown.join('; ')}`
}

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
// else), so this is a small local formatter instead, in the visitor's
// own local timezone rather than legacy's server-timezone `strftime` —
// an intentional, minor difference for what's purely an informational
// "when," not ledger data itself.
function formatBatchTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ImportPage() {
  const scenarios = useScenarios()
  const [recent, setRecent] = useState<RecentBatch[] | null>(null)
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Same exclusions as Scheduled's target-scenario picker (ScheduledPage.tsx)
  // and Import-with-rules' own — an import has to land somewhere it can
  // eventually become real postings.
  const eligibleScenarios = useMemo(
    () => (scenarios ?? []).filter((s) => !s.is_locked && !s.income_statement_only && !s.is_staging),
    [scenarios],
  )
  const firstScenarioId = eligibleScenarios[0]?.id ?? 0
  // `null` until the user actually picks one, derived rather than synced
  // via an effect — same reasoning ScheduledPage.tsx's own identical
  // `explicitScenarioId` gives (scenarios load asynchronously, so a
  // plain `useState(firstScenarioId)` would freeze at 0 forever).
  const [explicitScenarioId, setExplicitScenarioId] = useState<number | null>(null)
  const scenarioId = explicitScenarioId ?? firstScenarioId

  function reload() {
    client.GET('/import').then(({ data }) => {
      if (data) setRecent((data as unknown as { recent_batches: RecentBatch[] }).recent_batches)
    })
  }

  // Separate from `reload()` above (called again after a successful
  // upload) so the initial fetch can guard against setting state on an
  // unmounted component — same `cancelled` shape `AccountLevelsPage.tsx`/
  // `AccountsPage.tsx` already use for the identical local-fetch-plus-
  // reload pattern.
  useEffect(() => {
    let cancelled = false
    client.GET('/import').then(({ data }) => {
      if (!cancelled && data) setRecent((data as unknown as { recent_batches: RecentBatch[] }).recent_batches)
    })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file || !scenarioId) return
    setSubmitting(true)
    const body = new FormData()
    body.append('target_scenario_id', String(scenarioId))
    body.append('file', file)
    // openapi-fetch's own `defaultBodySerializer` passes a `FormData`
    // instance straight through unchanged (and skips the JSON
    // `Content-Type` header so the browser sets its own multipart
    // boundary) — the cast below is only to satisfy the generated
    // client's request-body type, which openapi-typescript can only
    // describe as `{ target_scenario_id: number; file: string }` (an
    // `UploadFile` has no better OpenAPI representation), not because
    // anything at runtime actually expects that shape.
    const { data, error } = await client.POST('/import', {
      body: body as unknown as { target_scenario_id: number; file: string },
    })
    setSubmitting(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not import the file') })
      return
    }
    const result = data as unknown as { staged_count: number; errors: string[] }
    const okMsg = `Staged ${result.staged_count} entr${result.staged_count === 1 ? 'y' : 'ies'} for review in Staging`
    setFlash({ ok: okMsg, err: result.errors.length ? skippedRowsMessage(result.errors) : undefined })
    setFile(null)
    reload()
  }

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          Imported entries land in <Link className="quiet-link" to="/app/staging">Staging</Link> for review,
          same as a scheduled entry.
        </p>
        {/* Plain `<a>`, not a `<Link>` — Help doesn't exist yet as this
            screen lands (it's the last screen this same phase builds);
            same "don't reach into a screen that doesn't exist yet"
            deferral every prior phase's own not-yet-built link already
            followed. Revisit once `HelpPage.tsx` ships later this phase. */}
        <a href="/help#import" className="help-icon" aria-label="How this works" title="How this works">?</a>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      <div className="panel">
        <h2>Upload a CSV</h2>
        <form className="grid-form" onSubmit={handleSubmit}>
          <label className="field">
            Target scenario
            <Combobox
              options={eligibleScenarios.map((s) => ({ value: String(s.id), label: `${s.code} — ${s.name}` }))}
              value={String(scenarioId)}
              onChange={(v) => setExplicitScenarioId(Number(v))}
            />
          </label>
          <label className="field" htmlFor="import-file-input" style={{ minWidth: '15rem' }}>
            CSV file
            <FileField id="import-file-input" name="file" accept=".csv,text/csv" required onFileChange={setFile} />
          </label>
          <button type="submit" disabled={submitting || !file}>Import</button>
        </form>
      </div>

      <p className="dim small">
        Have a single-entry export instead — one row per transaction, no debits/credits of its own (a budgeting
        app or bank export, say — ActualBudget&apos;s own CSV shape is the one this was built and tested
        against)?{' '}
        <Link className="quiet-link" to="/app/import/mapped">Import with rules</Link> maps it into double entry
        first.
      </p>

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
