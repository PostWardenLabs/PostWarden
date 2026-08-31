import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import Combobox from '../widgets/Combobox'
import FileField from '../widgets/FileField'
import NumberStepper from '../widgets/NumberStepper'
import { usePostableAccounts } from '../widgets/usePostableAccounts'

// The mapped importer's upload + column-mapping + review flow — split
// out of what used to be the whole of `ImportMappedPage.tsx` when the
// plain and mapped importers merged onto one page as two tabs
// (`ImportPage.tsx`'s own docstring has the reasoning). Three internal
// steps now, not two (`step` below) — BACKLOG.md's "New import with
// rules page" #2 added a column-mapping step between upload and review,
// since the importer used to require the file's own header row to read
// literally `Account,Date,Payee,Notes,Category,Amount` (true of
// ActualBudget's export by construction, false of anything else) — see
// `SPEC.md` decision 23's own account of why. None of these three steps
// exist as their own GET route — there's no server-side state between
// them to restore from on a refresh either, same reasoning the old
// two-step version already had — so this stays one component with
// internal `step` state, not three React Router routes.
//
// `errorDetail`/`ErrorBody`, `IMPORT_MAX_ERRORS_SHOWN`/
// `skippedRowsMessage` — identical to `ImportPlainPanel.tsx`'s own
// copies. Forked, not shared, same as that file's own comment on why:
// two three-line helpers each with exactly one caller isn't worth a
// shared module import cycle between two sibling panels.
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

// One entry of `service.IMPORT_MAPPED_FIELDS` — the backend's own
// target-field list (Money Account/Entry Date/Amount required; Payee/
// Entry Description/Line Memo/Category optional), read from `POST
// /import/mapped/columns`'s own response rather than duplicated here, so
// this screen's mapping step always matches whatever the backend
// actually validates against.
interface MappedField {
  key: string
  label: string
  required: boolean
}

// `service.IMPORT_DELIMITERS`/`IMPORT_DATE_FORMATS` — a picker-ready
// {key, label} pair, same shape `MappedField` already has.
interface DialectOption {
  key: string
  label: string
}

// `service.IMPORT_DEFAULT_DIALECT`'s own shape — the wizard's Phase 1
// step (IMPORT_WIZARD.md §3/§7 Phase 2): delimiter, how many leading
// lines to skip before the header, and how the file's own numbers/dates
// are written. Always a full object on this side of the wire — `service.
// resolve_dialect`'s docstring is the reason nothing here needs a
// partial-dialect type.
interface Dialect {
  delimiter: string
  header_row: number
  decimal_separator: string
  thousands_separator: string
  date_format: string
}

// The generated client types the wire's `dialect` as `dict[str, str |
// int]` (`schemas.py`'s own type — Pydantic has no way to say "exactly
// these five keys" over the wire), which TypeScript sees as an index
// signature, not `Dialect`'s five named fields. Giving `Dialect` itself
// that index signature would poison every `Partial<Dialect>` patch (an
// omitted key reads as `undefined`, which the index signature's `string
// | number` doesn't allow) — a plain cast at the three call sites that
// actually send a `Dialect` over the wire is simpler than fighting that.
type WireDialect = Record<string, string | number>

// What `POST /import/mapped/columns` hands back — the file's own real
// column names (in file order) plus a few real sample rows, so the
// column-mapping step can show actual data next to each target field
// instead of asking the user to guess from a header alone. `dialect` is
// the sniffed guess (R1); `delimiters`/`date_formats` are the dialect
// panel's own two enumerable option lists — decimal/thousands separator
// have no server-side option list because there are only ever two real
// choices each, enumerated locally below (`DECIMAL_SEPARATOR_OPTIONS`/
// `THOUSANDS_SEPARATOR_OPTIONS`).
interface ColumnsResult {
  columns: string[]
  sample_rows: Record<string, string>[]
  fields: MappedField[]
  dialect: Dialect
  delimiters: DialectOption[]
  date_formats: DialectOption[]
  filename: string
  target_scenario_id: number
  file_content_b64: string
}

// What `POST /import/mapped/columns/reparse` hands back — a subset of
// `ColumnsResult`: just what actually changes when the dialect does
// (`columns`/`sample_rows`/`dialect` itself), not the static option
// lists or the target-field list, which the first `/mapped/columns`
// call already handed over and can't change file to file.
interface ReparseResult {
  columns: string[]
  sample_rows: Record<string, string>[]
  dialect: Dialect
  filename: string
  target_scenario_id: number
  file_content_b64: string
}

// What `POST /import/mapped/preview` hands back — the picker lists plus
// the fields the commit step needs to carry forward unchanged
// (`filename`/`target_scenario_id`/`file_content_b64`/`column_map`/
// `dialect`), held in plain component state.
interface PreviewResult {
  row_count: number
  accounts_found: string[]
  categories_found: string[]
  has_no_category_rows: boolean
  filename: string
  target_scenario_id: number
  file_content_b64: string
  column_map: Record<string, string>
  dialect: Dialect
}

const CHOOSE = { value: '', label: '— choose —' }
const IGNORE = { value: '', label: '— ignore —' }

// `decimal_separator`/`thousands_separator` have no server-side option
// list (`service.py` never enumerates them — see `ColumnsResult`'s own
// comment above) because there are only ever two real-world choices
// each; small enough to hardcode here rather than round-trip a list the
// backend would just be echoing back unchanged.
const DECIMAL_SEPARATOR_OPTIONS = [
  { value: '.', label: 'Period ( 12.50 )' },
  { value: ',', label: 'Comma ( 12,50 )' },
]
const THOUSANDS_SEPARATOR_OPTIONS = [
  { value: '', label: '— none —' },
  { value: ',', label: 'Comma ( 1,234 )' },
  { value: '.', label: 'Period ( 1.234 )' },
]

interface ImportMappedPanelProps {
  // Called once a batch actually lands, so the container can re-fetch
  // the shared "Recent imports" table — same contract as
  // `ImportPlainPanel.tsx`'s own `onStaged`.
  onStaged: () => void
}

export default function ImportMappedPanel({ onStaged }: ImportMappedPanelProps) {
  const scenarios = useScenarios()
  const postable = usePostableAccounts(scenarios)
  const [step, setStep] = useState<'upload' | 'columns' | 'review'>('upload')
  const [flash, setFlash] = useState<{ ok?: string; err?: string } | null>(null)

  // Same exclusions as the plain Import panel's own target-scenario
  // picker (ImportPlainPanel.tsx) — an import has to land somewhere it
  // can eventually become real postings.
  const eligibleScenarios = useMemo(
    () => (scenarios ?? []).filter((s) => !s.is_locked && !s.income_statement_only && !s.is_staging),
    [scenarios],
  )
  const firstScenarioId = eligibleScenarios[0]?.id ?? 0
  const [explicitScenarioId, setExplicitScenarioId] = useState<number | null>(null)
  const scenarioId = explicitScenarioId ?? firstScenarioId

  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [columns, setColumns] = useState<ColumnsResult | null>(null)
  // The mapping step's own state, keyed the way the table now reads —
  // one entry per *file column*, value the target field key it's mapped
  // to ('' meaning Ignore). This is the inverse of what the wire format
  // (`column_map`, target-key -> column) wants; the inversion happens on
  // submit, in `handleColumnsSubmit`, which is also where a column-level
  // shape like this earns its keep — it's the only place two different
  // file columns picking the *same* target is still visible at all. Once
  // inverted into `column_map`'s target-keyed dict, a second claim on
  // one key would just silently overwrite the first (`service.
  // parse_mapped_file`'s own docstring has the same note from the other
  // side), so `duplicateTargetClaims` below has to be computed from this
  // state, not from the dict this state gets turned into.
  const [columnTargets, setColumnTargets] = useState<Record<string, string>>({})
  const [reparsing, setReparsing] = useState(false)
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
  // Each file-column row's own dropdown: every target field this file's
  // columns could be mapped onto, defaulting to Ignore. Options, not
  // values — unlike `accountOptions` this never depends on `columns`'
  // sample data, only on the target-field list itself.
  const targetOptions = useMemo(
    () => [IGNORE, ...(columns?.fields ?? []).map((f) => ({ value: f.key, label: f.label }))],
    [columns],
  )
  // Gates the column-mapping step's own submit — every `required` field
  // (Money Account/Entry Date/Amount) needs some column mapped to it
  // before there's anything worth previewing; the backend re-checks the
  // exact same thing (`service.parse_mapped_file`'s own
  // `missing_required`), this is purely so the button and the "still
  // needed" strip reflect it up front instead of round-tripping to find
  // out.
  const claimedTargetKeys = new Set(Object.values(columnTargets).filter(Boolean))
  const missingRequiredFields = (columns?.fields ?? []).filter((f) => f.required && !claimedTargetKeys.has(f.key))
  // The one thing the column-oriented table can express that the wire
  // format can't (see `columnTargets`' own comment above): two different
  // file columns both pointed at the same target. Grouped by target key
  // so the error can name every column involved, not just flag that a
  // clash exists.
  const targetClaims = new Map<string, string[]>()
  for (const [col, target] of Object.entries(columnTargets)) {
    if (!target) continue
    targetClaims.set(target, [...(targetClaims.get(target) ?? []), col])
  }
  const duplicateTargetClaims = [...targetClaims.entries()].filter(([, cols]) => cols.length > 1)

  async function handleUploadSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file || !scenarioId) return
    setUploading(true)
    setFlash(null)
    const body = new FormData()
    body.append('target_scenario_id', String(scenarioId))
    body.append('file', file)
    // Same `FormData`-passes-through-unchanged reasoning as
    // ImportPlainPanel.tsx's own identical cast — see that file's
    // comment for the openapi-fetch source dig this is based on.
    const { data, error } = await client.POST('/import/mapped/columns', {
      body: body as unknown as { target_scenario_id: number; file: string },
    })
    setUploading(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not read that file') })
      return
    }
    setColumns(data as unknown as ColumnsResult)
    setColumnTargets({})
    setStep('columns')
  }

  // The dialect panel's own live re-parse (IMPORT_WIZARD.md §7 Phase 2
  // item 5, R2) — re-reads the *same already-uploaded* file
  // (`file_content_b64` never changes here) against `columns.dialect`
  // patched with whatever control the user just touched. Column targets
  // only get dropped when the columns a delimiter/header-row edit
  // produced actually differ from before — a decimal-separator or
  // date-format edit alone never changes what the columns are, so a
  // mapping already made shouldn't vanish just because of it.
  async function handleDialectChange(patch: Partial<Dialect>) {
    if (!columns) return
    const dialect = { ...columns.dialect, ...patch }
    setReparsing(true)
    setFlash(null)
    const { data, error } = await client.POST('/import/mapped/columns/reparse', {
      body: {
        filename: columns.filename, target_scenario_id: columns.target_scenario_id,
        file_content_b64: columns.file_content_b64, dialect: dialect as unknown as WireDialect,
      },
    })
    setReparsing(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not re-read that file with this format') })
      return
    }
    const result = data as unknown as ReparseResult
    const columnsChanged = result.columns.length !== columns.columns.length
      || result.columns.some((c, i) => c !== columns.columns[i])
    setColumns((c) => c && { ...c, columns: result.columns, sample_rows: result.sample_rows, dialect: result.dialect })
    if (columnsChanged) setColumnTargets({})
  }

  async function handleColumnsSubmit(e: FormEvent) {
    e.preventDefault()
    if (!columns || missingRequiredFields.length || duplicateTargetClaims.length) return
    // Invert column->target into the wire's target->column shape. Safe
    // to do with a plain assignment (rather than guarding each write)
    // because the button above is already disabled while
    // `duplicateTargetClaims` is non-empty — nothing here silently drops
    // a second claim on the same key without the user having already
    // been shown which columns clash.
    const column_map: Record<string, string> = {}
    for (const [col, target] of Object.entries(columnTargets)) {
      if (target) column_map[target] = col
    }
    setPreviewing(true)
    setFlash(null)
    const { data, error } = await client.POST('/import/mapped/preview', {
      body: {
        filename: columns.filename, target_scenario_id: columns.target_scenario_id,
        file_content_b64: columns.file_content_b64, column_map,
        dialect: columns.dialect as unknown as WireDialect,
      },
    })
    setPreviewing(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not read that file with this mapping') })
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
        column_map: preview.column_map,
        dialect: preview.dialect as unknown as WireDialect,
        account_map: accountMap,
        category_map: categoryMap,
        flip_sign: flipSign,
      },
    })
    setCommitting(false)
    if (error) {
      // Stays on this same review step rather than bouncing back to the
      // upload step — the mappings are still right here in component
      // state, there's no server-side state between any of these steps
      // to restore from either way (see the `errors: string[]` shape
      // below: the round trip is client-held state, not a stored row).
      setFlash({ err: errorDetail(error, 'Could not stage those rows') })
      return
    }
    const result = data as unknown as { staged_count: number; errors: string[] }
    const okMsg = `Staged ${result.staged_count} entr${result.staged_count === 1 ? 'y' : 'ies'} for review in Staging`
    setFlash({ ok: okMsg, err: result.errors.length ? skippedRowsMessage(result.errors) : undefined })
    setFile(null)
    setColumns(null)
    setPreview(null)
    setStep('upload')
    onStaged()
  }

  function startOver() {
    setFile(null)
    setColumns(null)
    setColumnTargets({})
    setPreview(null)
    setFlash(null)
    setStep('upload')
  }

  return (
    <>
      {step === 'upload' && (
        <>
          <p className="page-sub">
            For single-entry exports — one row per transaction, no debit/credit of their own — from whatever
            budgeting app or bank export produces that shape; ActualBudget&apos;s own CSV export is the one this
            was built and tested against, but any single-entry CSV works the same way once its own columns are
            mapped in the next step. Map each Account and Category value to a real PostWarden account once, and
            every row gets turned into a proper double-entry posting, staged in{' '}
            <Link className="quiet-link" to="/app/staging">Staging</Link> for review same as any other import.
          </p>

          {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

          <div className="panel">
            <h2>Upload a single-entry CSV</h2>
            <p className="dim small">
              Whatever columns your file already has — Account/Date/Payee/Notes/Category/Amount, or your bank's
              own names for the same things — the next step maps them onto what this importer needs.
            </p>
            <form className="grid-form" onSubmit={handleUploadSubmit}>
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
              <button type="submit" disabled={uploading || !file}>
                {uploading ? 'Reading…' : 'Next: map columns'}
              </button>
            </form>
          </div>
        </>
      )}

      {step === 'columns' && columns && (
        <>
          <p className="page-sub">
            {columns.filename} — {columns.columns.length} column{columns.columns.length === 1 ? '' : 's'} found.
            Every one of the file's own columns is listed below; map each to whichever PostWarden field it holds,
            or leave it as Ignore. The sample values are this file's own first few rows, to help tell columns
            with similar names apart.
          </p>

          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

          {/* The dialect panel (IMPORT_WIZARD.md §3 step 1, §7 Phase 2)
              — sniffed on upload, editable here, re-parsing the same
              already-uploaded file live on every change (R2: the
              columns/sample values below are always this file's real
              data under whatever dialect is currently chosen, never a
              stale snapshot from the initial guess). Deliberately
              outside `handleColumnsSubmit`'s own <form> below — these
              controls have nothing to do with that form's own submit,
              and keeping them separate means an Enter press in the
              header-row stepper can't accidentally trigger it. */}
          <div className="panel">
            <h2>File format</h2>
            <p className="dim small">
              Sniffed from the file itself — usually right, always editable. Changing any of these re-reads the
              file below, so you can see the effect immediately.
            </p>
            <div className="grid-form">
              <label className="field">
                Column delimiter
                <Combobox
                  options={columns.delimiters.map((d) => ({ value: d.key, label: d.label }))}
                  value={columns.dialect.delimiter}
                  onChange={(v) => handleDialectChange({ delimiter: v })}
                  disabled={reparsing}
                />
              </label>
              <label className="field" style={{ maxWidth: '11rem' }}>
                Skip leading row(s)
                <NumberStepper
                  min={0}
                  max={20}
                  value={String(columns.dialect.header_row)}
                  onChange={(v) => handleDialectChange({ header_row: Math.max(0, Number(v) || 0) })}
                  disabled={reparsing}
                />
              </label>
              <label className="field">
                Decimal separator
                <Combobox
                  options={DECIMAL_SEPARATOR_OPTIONS}
                  value={columns.dialect.decimal_separator}
                  onChange={(v) => handleDialectChange({ decimal_separator: v })}
                  disabled={reparsing}
                />
              </label>
              <label className="field">
                Thousands separator
                <Combobox
                  options={THOUSANDS_SEPARATOR_OPTIONS}
                  value={columns.dialect.thousands_separator}
                  onChange={(v) => handleDialectChange({ thousands_separator: v })}
                  disabled={reparsing}
                />
              </label>
              <label className="field">
                Date format
                <Combobox
                  options={columns.date_formats.map((d) => ({ value: d.key, label: d.label }))}
                  value={columns.dialect.date_format}
                  onChange={(v) => handleDialectChange({ date_format: v })}
                  disabled={reparsing}
                />
              </label>
            </div>
            {reparsing && <p className="dim small" style={{ marginTop: '0.5rem' }}>Re-reading…</p>}
          </div>

          <form onSubmit={handleColumnsSubmit}>
            <div className="panel">
              <h2>Map this file's columns</h2>
              {/* One row per column found in the file (IMPORT_WIZARD.md §2)
                  — every column gets an explicit decision, defaulting to
                  Ignore, rather than the old target-field-oriented table
                  silently dropping whatever a user never picked. */}
              <div style={{ overflowX: 'auto' }}>
                <table className="ledger">
                  <thead><tr><th>Import file column</th><th>Sample value</th><th>Target data field</th></tr></thead>
                  <tbody>
                    {columns.columns.map((c) => (
                      <tr key={c}>
                        <td className="mono">{c}</td>
                        <td className="dim">
                          {columns.sample_rows.slice(0, 3).map((r) => r[c] || '—').join(', ')}
                        </td>
                        <td>
                          <Combobox
                            options={targetOptions}
                            value={columnTargets[c] ?? ''}
                            onChange={(v) => setColumnTargets((m) => ({ ...m, [c]: v }))}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {!!missingRequiredFields.length && (
                <p className="dim small" style={{ marginTop: '0.8rem' }}>
                  Still needed: {missingRequiredFields.map((f) => f.label).join(', ')}
                </p>
              )}
              {duplicateTargetClaims.map(([target, cols]) => (
                <p className="flash flash-err" key={target} style={{ marginTop: '0.8rem' }}>
                  {cols.slice(0, -1).join(', ')}{cols.length > 2 ? ',' : ''} and {cols[cols.length - 1]} are
                  {cols.length > 2 ? ' all' : ' both'} mapped to{' '}
                  {columns.fields.find((f) => f.key === target)?.label ?? target} — pick one.
                </p>
              ))}

              <button type="submit" disabled={previewing || reparsing || !!missingRequiredFields.length
                                               || !!duplicateTargetClaims.length}
                      style={{ marginTop: '0.8rem' }}>
                {previewing ? 'Reading…' : 'Next: map accounts & categories'}
              </button>
              <button type="button" className="quiet" style={{ marginLeft: '0.5rem' }} onClick={startOver}>
                Start over
              </button>
            </div>
          </form>
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

          {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

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
