import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import Combobox from '../widgets/Combobox'
import FileField from '../widgets/FileField'
import { usePostableAccounts } from '../widgets/usePostableAccounts'

// The mapped importer's upload + review flow. The review step only ever
// exists as `POST /import/mapped/preview`'s response body — there's no
// GET route for it — so this is one component with two internal steps
// (`step` below), not two React Router routes.
//
// `errorDetail`/`ErrorBody`, `IMPORT_MAX_ERRORS_SHOWN`/
// `skippedRowsMessage` — identical to `ImportPage.tsx`'s own copies.
// Forked, not shared, same as that file's own comment on why: two
// three-line helpers each with exactly one caller isn't worth a shared
// module import cycle between two sibling screens.
interface ErrorBody {
  detail?: string
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as ErrorBody | undefined)?.detail || fallback
}

const IMPORT_MAX_ERRORS_SHOWN = 20

function skippedRowsMessage(errors: string[]): string {
  const shown = errors.slice(0, IMPORT_MAX_ERRORS_SHOWN)
  if (errors.length > shown.length) shown.push(`...and ${errors.length - shown.length} more`)
  return `${errors.length} row(s) skipped: ${shown.join('; ')}`
}

// What `POST /import/mapped/preview` hands back — the picker lists plus
// the three fields the commit step needs to carry forward unchanged
// (`filename`/`target_scenario_id`/`file_content_b64`), held in plain
// component state.
interface PreviewResult {
  row_count: number
  accounts_found: string[]
  categories_found: string[]
  has_no_category_rows: boolean
  filename: string
  target_scenario_id: number
  file_content_b64: string
}

const CHOOSE = { value: '', label: '— choose —' }

export default function ImportMappedPage() {
  const scenarios = useScenarios()
  const postable = usePostableAccounts(scenarios)
  const [step, setStep] = useState<'upload' | 'review'>('upload')
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  // Same exclusions as the plain Import screen's own target-scenario
  // picker (ImportPage.tsx) — an import has to land somewhere it can
  // eventually become real postings.
  const eligibleScenarios = useMemo(
    () => (scenarios ?? []).filter((s) => !s.is_locked && !s.income_statement_only && !s.is_staging),
    [scenarios],
  )
  const firstScenarioId = eligibleScenarios[0]?.id ?? 0
  const [explicitScenarioId, setExplicitScenarioId] = useState<number | null>(null)
  const scenarioId = explicitScenarioId ?? firstScenarioId

  const [file, setFile] = useState<File | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)

  // The map's own key is the file's raw Account/Category value, the
  // value is the real account's *code* (not id) — `transform_mapped_rows`
  // on the backend
  // looks values up by code, matching `postable_accounts_for_pickers`'
  // own `<option value="{{ p.code }}">`. `IMPORT_MAPPED_NO_CATEGORY`
  // (empty string) is the "(no category)" row's own key, same on both
  // sides of the wire.
  const [accountMap, setAccountMap] = useState<Record<string, string>>({})
  const [categoryMap, setCategoryMap] = useState<Record<string, string>>({})
  const [flipSign, setFlipSign] = useState(false)
  const [committing, setCommitting] = useState(false)

  const accountOptions = useMemo(
    () => [CHOOSE, ...(postable?.forPickers ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))],
    [postable],
  )

  async function handlePreviewSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file || !scenarioId) return
    setPreviewing(true)
    setFlash(null)
    const body = new FormData()
    body.append('target_scenario_id', String(scenarioId))
    body.append('file', file)
    // Same `FormData`-passes-through-unchanged reasoning as ImportPage.tsx's
    // own identical cast — see that file's comment for the openapi-fetch
    // source dig this is based on.
    const { data, error } = await client.POST('/import/mapped/preview', {
      body: body as unknown as { target_scenario_id: number; file: string },
    })
    setPreviewing(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not read that file') })
      return
    }
    setPreview(data as unknown as PreviewResult)
    setAccountMap({})
    setCategoryMap({})
    setFlipSign(false)
    setStep('review')
  }

  async function handleCommitSubmit(e: FormEvent) {
    e.preventDefault()
    if (!preview) return
    setCommitting(true)
    const { data, error } = await client.POST('/import/mapped', {
      body: {
        filename: preview.filename,
        target_scenario_id: preview.target_scenario_id,
        file_content_b64: preview.file_content_b64,
        account_map: accountMap,
        category_map: categoryMap,
        flip_sign: flipSign,
      },
    })
    setCommitting(false)
    if (error) {
      // Stays on this same review step rather than bouncing back to the
      // upload step — the mappings are still right here in component
      // state, there's no server-side state between the two steps to
      // restore from either way (see the `errors: string[]` shape below:
      // the round trip is client-held state, not a stored row).
      setFlash({ err: errorDetail(error, 'Could not stage those rows') })
      return
    }
    const result = data as unknown as { staged_count: number; errors: string[] }
    const okMsg = `Staged ${result.staged_count} entr${result.staged_count === 1 ? 'y' : 'ies'} for review in Staging`
    setFlash({ ok: okMsg, err: result.errors.length ? skippedRowsMessage(result.errors) : undefined })
    setFile(null)
    setPreview(null)
    setStep('upload')
  }

  function startOver() {
    setFile(null)
    setPreview(null)
    setFlash(null)
    setStep('upload')
  }

  return (
    <>
      <div className="page-head">
        <p className="page-sub">
          For single-entry exports — one row per transaction, no debit/credit of their own — from whatever
          budgeting app or bank export produces that shape; ActualBudget&apos;s own CSV export is the one this
          was built and tested against. Map each Account and Category value to a real PostWarden account once,
          and every row gets turned into a proper double-entry posting, staged in{' '}
          <Link className="quiet-link" to="/app/staging">Staging</Link> for review same as any other import.
        </p>
        <Link to="/app/help#import" className="help-icon" aria-label="How this works" title="How this works">?</Link>
      </div>

      {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash?.err && <div className="flash flash-err">{flash.err}</div>}

      {step === 'upload' && (
        <>
          <div className="panel">
            <h2>Upload a single-entry CSV</h2>
            <p className="dim small">
              Expected columns: <span className="mono">Account, Date, Payee, Notes, Category, Amount</span> —
              exactly what ActualBudget&apos;s own CSV export produces, but any file with those same column
              names works the same way, whatever produced it. <span className="mono">Date</span> must be{' '}
              <span className="mono">YYYY-MM-DD</span>.
            </p>
            <form className="grid-form" onSubmit={handlePreviewSubmit}>
              <label className="field">
                Target scenario
                <Combobox
                  options={eligibleScenarios.map((s) => ({ value: String(s.id), label: `${s.code} — ${s.name}` }))}
                  value={String(scenarioId)}
                  onChange={(v) => setExplicitScenarioId(Number(v))}
                />
              </label>
              <label className="field" htmlFor="import-mapped-file-input" style={{ minWidth: '15rem' }}>
                CSV file
                <FileField
                  id="import-mapped-file-input"
                  name="file"
                  accept=".csv,text/csv"
                  required
                  onFileChange={setFile}
                />
              </label>
              <button type="submit" disabled={previewing || !file}>
                {previewing ? 'Reading…' : 'Next: map accounts & categories'}
              </button>
            </form>
          </div>

          <p className="dim small" style={{ marginTop: '1rem' }}>
            Already have a file with real debits and credits per line? Use the plain{' '}
            <Link className="quiet-link" to="/app/import">Import</Link> instead.
          </p>
        </>
      )}

      {step === 'review' && preview && (
        <>
          <p className="page-sub">
            {preview.filename} — {preview.row_count} row{preview.row_count === 1 ? '' : 's'} found. Map each
            value below to a real PostWarden account, then Stage — every row becomes one balanced double-entry
            posting in <Link className="quiet-link" to="/app/staging">Staging</Link>. Leave a value unmapped to
            skip every row that uses it (reported, not silently dropped).
          </p>

          <form onSubmit={handleCommitSubmit}>
            <div className="panel">
              <h2>Account — which is the money side?</h2>
              <p className="dim small">Whichever real bank/credit-card account each of these represents.</p>
              <table className="ledger">
                <thead><tr><th>Found in file</th><th>Maps to</th></tr></thead>
                <tbody>
                  {preview.accounts_found.map((a) => (
                    <tr key={a}>
                      <td className="mono">{a}</td>
                      <td>
                        <Combobox
                          options={accountOptions}
                          value={accountMap[a] ?? ''}
                          onChange={(v) => setAccountMap((m) => ({ ...m, [a]: v }))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="panel">
              <h2>Category — which account is the other side?</h2>
              <p className="dim small">
                The expense/income account each category represents. &quot;(no category)&quot; covers
                transfers/withdrawals and anything else this export left blank — map it to whichever single
                account fits most of those rows, or leave it unmapped to skip them all.
              </p>
              <table className="ledger">
                <thead><tr><th>Found in file</th><th>Maps to</th></tr></thead>
                <tbody>
                  {preview.has_no_category_rows && (
                    <tr>
                      <td className="dim italic">(no category)</td>
                      <td>
                        <Combobox
                          options={accountOptions}
                          value={categoryMap[''] ?? ''}
                          onChange={(v) => setCategoryMap((m) => ({ ...m, '': v }))}
                        />
                      </td>
                    </tr>
                  )}
                  {preview.categories_found.map((c) => (
                    <tr key={c}>
                      <td className="mono">{c}</td>
                      <td>
                        <Combobox
                          options={accountOptions}
                          value={categoryMap[c] ?? ''}
                          onChange={(v) => setCategoryMap((m) => ({ ...m, [c]: v }))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="panel">
              <label className="checkline">
                <input type="checkbox" checked={flipSign} onChange={(e) => setFlipSign(e.target.checked)} />
                Flip Amount&apos;s sign (check this if a normal expense shows as a positive number in your file
                instead of negative)
              </label>
              <button type="submit" disabled={committing} style={{ marginTop: '0.8rem' }}>
                {committing ? 'Staging…' : `Stage ${preview.row_count} row${preview.row_count === 1 ? '' : 's'}`}
              </button>
              {/* A real `<button>`, not an `<a class="button-link quiet">`
                  — "start over" resets this component's own state, it
                  doesn't navigate anywhere, and a plain `button.quiet`
                  actually gets index.css's `.quiet` styling (it only
                  targets the element selector, so an anchor with both
                  classes would render as a plain `.button-link` with
                  `.quiet` doing nothing). */}
              <button type="button" className="quiet" style={{ marginLeft: '0.5rem' }} onClick={startOver}>
                Start over
              </button>
            </div>
          </form>
        </>
      )}
    </>
  )
}
