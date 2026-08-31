import { useMemo, useState, type FormEvent } from 'react'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import Combobox from '../widgets/Combobox'
import FileField from '../widgets/FileField'

// The plain double-entry CSV importer's own panel — split out of what
// used to be the whole of `ImportPage.tsx` when that file grew a second
// tab (`ImportMappedPanel.tsx`); the page-head, tab bar, and shared
// "Recent imports" table all moved up to the new `ImportPage.tsx`
// container, which is why this only ever renders its own upload panel.
//
// `errorDetail`/`ErrorBody` — same local cast-from-`unknown` shape every
// write-route screen in this app carries (`PayeesPage.tsx` and onward),
// since FastAPI's plain `HTTPException(400, detail=...)` isn't typed any
// more specifically than that in the generated client.
interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

// `IMPORT_MAX_ERRORS_SHOWN` — mirrors `modules/imports/service.py`'s own
// constant of the same value (20). The backend's success response
// returns every row error, untruncated (`import_csv`'s own `errors` is
// the full list); `service.import_csv` just returns data, it doesn't
// format a message, so this screen does the truncate-and-append-"...and
// N more" formatting instead — identical logic to Import-with-rule's own
// review step, which needs the same truncation for the same reason and
// forks it rather than sharing a one-off helper for two callers.
const IMPORT_MAX_ERRORS_SHOWN = 20

function skippedRowsMessage(errors: string[]): string {
  const shown = errors.slice(0, IMPORT_MAX_ERRORS_SHOWN)
  if (errors.length > shown.length) shown.push(`...and ${errors.length - shown.length} more`)
  return `${errors.length} row(s) skipped: ${shown.join('; ')}`
}

interface ImportPlainPanelProps {
  // Called once a batch actually lands, so the container can re-fetch
  // the shared "Recent imports" table — this panel doesn't know that
  // table exists, same "child does the write, parent owns the shared
  // list" split `ImportMappedPanel.tsx` also follows.
  onStaged: () => void
}

export default function ImportPlainPanel({ onStaged }: ImportPlainPanelProps) {
  const scenarios = useScenarios()
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
    onStaged()
  }

  return (
    <>
      <p className="page-sub">
        For an export that already has real debits and credits per line — one row per posting, two-plus rows
        per entry, already balanced.
      </p>

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
    </>
  )
}
