import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'
import { useScenarios } from '../api/useScenarios'
import Combobox from '../widgets/Combobox'
import FileField from '../widgets/FileField'
import NumberStepper from '../widgets/NumberStepper'
import { usePostableAccounts } from '../widgets/usePostableAccounts'

// The unified importer's upload + shape/column-mapping + review flow —
// split out of what used to be the whole of `ImportMappedPage.tsx` when
// the plain and mapped importers merged onto one page as two tabs
// (`ImportPage.tsx`'s own docstring has the reasoning), then absorbed the
// plain importer's own grouped/Debit-Credit shape entirely in IMPORT_
// WIZARD.md §7 Phase 4 — this is now the *only* importer's own UI, though
// `ImportPage.tsx` still mounts it alongside `ImportPlainPanel.tsx` as a
// tab until Phase 4.7 retires that panel and its route for good. Up to
// four internal steps now (`step` below) — BACKLOG.md's "New import with
// rules page" #2 added a column-mapping step between upload and review,
// since the importer used to require the file's own header row to read
// literally `Account,Date,Payee,Notes,Category,Amount` (true of
// ActualBudget's export by construction, false of anything else) — see
// `SPEC.md` decision 23's own account of why; a fourth, `'validate'`,
// only ever renders when the review step's own pre-commit check (IMPORT_
// WIZARD.md §7 Phase 3) finds row errors — a clean file never sees it.
// None of these steps exist as their own GET route — there's no
// server-side state between them to restore from on a refresh either,
// same reasoning the old two-step version already had — so this stays
// one component with internal `step` state, not separate React Router
// routes.
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

// `service.transform_rows`' own per-row error shape (IMPORT_WIZARD.md §7
// Phase 3 item 1) — structured, not a pre-joined "Row N: ..." string, so
// the validation-report table below can render `raw`'s own field values
// next to `message` as separate columns. `raw` is the row exactly as
// `parse_file` produced it — still-unparsed strings for whichever fields
// got mapped.
interface RowError {
  row_no: number
  raw: Record<string, string>
  message: string
}

function skippedRowsMessage(errors: RowError[]): string {
  const shown = errors.slice(0, IMPORT_MAX_ERRORS_SHOWN).map((e) => `Row ${e.row_no}: ${e.message}`)
  if (errors.length > shown.length) shown.push(`...and ${errors.length - shown.length} more`)
  return `${errors.length} row(s) skipped: ${shown.join('; ')}`
}

// One entry of a `service.target_fields_for_shape(shape)` result — the
// backend's own target-field list for whichever shape is currently
// chosen, read from `POST /import/mapped/columns`'s own response
// (`fields_by_shape`, every shape's list precomputed) rather than
// duplicated here, so this screen's mapping step always matches whatever
// the backend actually validates against. `lookup_capable` (IMPORT_
// WIZARD.md §7 Phase 4 item 2) — only `account`/`category` are ever
// `true`; only those can carry a `column_kinds` entry at all.
interface MappedField {
  key: string
  label: string
  required: boolean
  lookup_capable: boolean
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

// `service.IMPORT_DEFAULT_SHAPE`'s own shape (IMPORT_WIZARD.md §7 Phase 4
// item 1) — "grouped rows vs one row per entry" and "Debit/Credit columns
// vs one signed Amount column" are wizard settings now, not a choice of
// importer. `group_key_column` is only ever `sniff_shape`'s own initial
// guess at which file column looks like the grouping key — once the user
// reaches the columns step, the actual grouping column is just another
// mapping choice (`groupKeyColumn` state below), not re-derived from this
// field again.
interface Shape {
  rows_per_entry: string
  group_key_column: string | null
  amount_style: string
}

function shapeKey(s: Shape): string {
  return `${s.rows_per_entry}:${s.amount_style}`
}

// The generated client types `dialect`/`shape` as `dict[str, str | int]`/
// `dict[str, str | None]` (`schemas.py`'s own types — Pydantic has no way
// to say "exactly these named keys" over the wire), which TypeScript sees
// as an index signature, not the named-field interfaces above. Giving
// `Dialect`/`Shape` themselves that index signature would poison every
// partial patch (an omitted key reads as `undefined`, which the index
// signature doesn't allow) — a plain cast at the call sites that actually
// send one of these over the wire is simpler than fighting that.
type WireDialect = Record<string, string | number>
type WireShape = Record<string, string | null>

// What `POST /import/mapped/columns` hands back — the file's own real
// column names (in file order) plus a few real sample rows, so the
// column-mapping step can show actual data next to each target field
// instead of asking the user to guess from a header alone. `dialect` and
// `shape` are both sniffed guesses (R1); `delimiters`/`date_formats` are
// the dialect panel's own two enumerable option lists — decimal/
// thousands separator have no server-side option list because there are
// only ever two real choices each, enumerated locally below
// (`DECIMAL_SEPARATOR_OPTIONS`/`THOUSANDS_SEPARATOR_OPTIONS`).
// `fields_by_shape` is every shape's own target-field list, precomputed —
// switching `rows_per_entry`/`amount_style` in the Shape panel below
// never needs a round trip to find out what fields that shape offers
// (`service.target_fields_by_shape`'s own docstring).
interface ColumnsResult {
  columns: string[]
  sample_rows: Record<string, string>[]
  shape: Shape
  fields_by_shape: Record<string, MappedField[]>
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
// lists or the target-field lists, which the first `/mapped/columns`
// call already handed over and can't change file to file. No `shape`
// here either — a dialect edit never invalidates it (`schemas.
// MappedColumnsReparseRequest`'s own docstring).
interface ReparseResult {
  columns: string[]
  sample_rows: Record<string, string>[]
  dialect: Dialect
  filename: string
  target_scenario_id: number
  file_content_b64: string
}

// One `values_found` entry (`service.preview_file`'s own docstring) —
// every raw value a `"label"`-kind lookup column actually holds, plus
// whether any row left it blank.
interface ValuesFound {
  distinct: string[]
  has_blank_rows: boolean
}

// What `POST /import/mapped/preview` hands back — `values_found`
// generalizes the old hardcoded `accounts_found`/`categories_found`/
// `has_no_category_rows` into "however many lookup-needing columns the
// mapping declares" (0, 1, or 2 in practice, since only `account`/
// `category` are ever `lookup_capable` — a fully `"code"`-kind mapping
// comes back with an empty object, and the review step below renders
// zero lookup tables for it), plus the fields the commit step needs to
// carry forward unchanged (`filename`/`target_scenario_id`/
// `file_content_b64`/`shape`/`column_map`/`column_kinds`/`dialect`),
// held in plain component state.
interface PreviewResult {
  row_count: number
  values_found: Record<string, ValuesFound>
  filename: string
  target_scenario_id: number
  file_content_b64: string
  shape: Shape
  column_map: Record<string, string>
  column_kinds: Record<string, string>
  dialect: Dialect
}

// What `POST /import/mapped/validate` hands back (IMPORT_WIZARD.md §3
// step 5, §7 Phase 3) — the review step's own pre-commit check, run with
// the value maps that step just collected. `groups_count` is how many
// entries would actually stage; `errors` is empty for a clean file, in
// which case the frontend skips straight to committing without ever
// showing the validation-report step (R1). Everything else is the same
// round-tripped shape `commit()` below needs to actually stage —
// including `value_maps`/`flip_sign` this time, since (unlike
// `PreviewResult`) those choices already exist by this step.
interface ValidateResult {
  groups_count: number
  errors: RowError[]
  filename: string
  target_scenario_id: number
  file_content_b64: string
  shape: Shape
  column_map: Record<string, string>
  column_kinds: Record<string, string>
  dialect: Dialect
  value_maps: Record<string, Record<string, string>>
  flip_sign: boolean
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

// The Shape panel's own two toggles (IMPORT_WIZARD.md §7 Phase 4 item 1)
// — plain `Combobox` pickers, same widget every other binary/enum choice
// on this screen already uses (delimiter, decimal separator, date
// format), rather than inventing a dedicated segmented-toggle widget for
// just these two.
const ROWS_PER_ENTRY_OPTIONS = [
  { value: 'one', label: 'One row per entry' },
  { value: 'grouped', label: 'Grouped rows (one row per leg)' },
]
const AMOUNT_STYLE_OPTIONS = [
  { value: 'signed', label: 'One signed Amount column' },
  { value: 'debit_credit', label: 'Separate Debit / Credit columns' },
]

// `columnKinds`' own two values (IMPORT_WIZARD.md §7 Phase 4 item 2) —
// whether a `lookup_capable` column's cells already hold a real account
// code or a label needing a `value_maps` lookup in the review step.
const COLUMN_KIND_OPTIONS = [
  { value: 'label', label: 'Labels to map' },
  { value: 'code', label: 'Account codes' },
]

// The code/label default heuristic (IMPORT_WIZARD.md §7 Phase 4 item 2)
// — a structural guess from `shape` alone, not a live check against real
// account codes (keeps `parse_file`/`transform_rows` genuinely
// `Connection`-free, R12): only the historical Export-CSV shape (grouped,
// Debit/Credit, `Account code` cells hold real codes) defaults to
// `"code"`, so that round trip stays zero-friction the way it always
// was; every other shape defaults to `"label"`, same as the old mapped
// importer always assumed.
function defaultColumnKind(targetKey: string, shape: Shape): 'code' | 'label' {
  if (targetKey === 'account' && shape.rows_per_entry === 'grouped' && shape.amount_style === 'debit_credit') {
    return 'code'
  }
  return 'label'
}

interface ImportMappedPanelProps {
  // Called once a batch actually lands, so the container can re-fetch
  // the shared "Recent imports" table — same contract as
  // `ImportPlainPanel.tsx`'s own `onStaged`.
  onStaged: () => void
}

export default function ImportMappedPanel({ onStaged }: ImportMappedPanelProps) {
  const scenarios = useScenarios()
  const postable = usePostableAccounts(scenarios)
  const [step, setStep] = useState<'upload' | 'columns' | 'review' | 'validate'>('upload')
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
  // The Shape panel's own editable state (IMPORT_WIZARD.md §7 Phase 4
  // item 1) — seeded from `columns.shape`'s sniffed guess on upload, but
  // never re-derived from it after that: a shape edit is 100%
  // client-side (`ColumnsResult`'s own comment), so this has to live
  // apart from `columns` rather than as one of its fields the way
  // `dialect` does (dialect edits round-trip through `/mapped/columns/
  // reparse`; shape edits never call the backend at all).
  const [shape, setShape] = useState<Shape>({ rows_per_entry: 'one', group_key_column: null, amount_style: 'signed' })
  // The Shape panel's dedicated "which column identifies each entry"
  // picker — a real file column name, or '' when unset. Kept apart from
  // `columnTargets` below (rather than `'group_key'` being just another
  // claimable target in that table) since it's the one field central
  // enough to the shape decision itself to deserve its own prominent
  // control right where `rows_per_entry` is chosen, not buried as one
  // more row in the general mapping table.
  const [groupKeyColumn, setGroupKeyColumn] = useState('')
  // The mapping step's own state, keyed the way the table now reads —
  // one entry per *file column*, value the target field key it's mapped
  // to ('' meaning Ignore). This is the inverse of what the wire format
  // (`column_map`, target-key -> column) wants; the inversion happens on
  // submit, in `handleColumnsSubmit`, which is also where a column-level
  // shape like this earns its keep — it's the only place two different
  // file columns picking the *same* target is still visible at all. Once
  // inverted into `column_map`'s target-keyed dict, a second claim on
  // one key would just silently overwrite the first (`service.
  // parse_file`'s own docstring has the same note from the other side),
  // so `duplicateTargetClaims` below has to be computed from this state,
  // not from the dict this state gets turned into.
  const [columnTargets, setColumnTargets] = useState<Record<string, string>>({})
  // A parallel column-keyed map (IMPORT_WIZARD.md §7 Phase 4 item 2) —
  // only meaningful for a column whose current target is `lookup_capable`
  // (defaults per `defaultColumnKind` otherwise); inverted into the
  // wire's target-keyed `column_kinds` alongside `column_map`'s own
  // inversion.
  const [columnKinds, setColumnKinds] = useState<Record<string, 'code' | 'label'>>({})
  const [reparsing, setReparsing] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)

  // One lookup map per `values_found` key (IMPORT_WIZARD.md §7 Phase 4
  // item 2 — generalizes the old separate `accountMap`/`categoryMap`
  // state into "however many lookup-needing fields this mapping has").
  // Each inner map's own key is the file's raw value, the value is the
  // real account's *code* (not id) — `transform_rows` on the backend
  // looks values up by code, matching `postable_accounts_for_pickers`'
  // own `<option value="{{ p.code }}">`. `service.IMPORT_NO_VALUE_KEY`
  // (empty string) is the "(blank)"/"(no category)" row's own key, same
  // on both sides of the wire.
  const [valueMaps, setValueMaps] = useState<Record<string, Record<string, string>>>({})
  const [flipSign, setFlipSign] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState<ValidateResult | null>(null)
  const [committing, setCommitting] = useState(false)

  const accountOptions = useMemo(
    () => [CHOOSE, ...(postable?.forPickers ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))],
    [postable],
  )
  // Every target field the currently-chosen shape offers (`service.
  // target_fields_for_shape`, precomputed for all four shapes as
  // `fields_by_shape`) — minus `group_key`, which the Shape panel's own
  // dedicated picker handles instead of a row in this table.
  const tableFields = useMemo(
    () => (columns?.fields_by_shape[shapeKey(shape)] ?? []).filter((f) => f.key !== 'group_key'),
    [columns, shape],
  )
  const groupKeyField = (columns?.fields_by_shape[shapeKey(shape)] ?? []).find((f) => f.key === 'group_key')
  // Each file-column row's own dropdown: every target field this file's
  // columns could be mapped onto, defaulting to Ignore. Options, not
  // values — unlike `accountOptions` this never depends on `columns`'
  // sample data, only on the current shape's own target-field list.
  const targetOptions = useMemo(
    () => [IGNORE, ...tableFields.map((f) => ({ value: f.key, label: f.label }))],
    [tableFields],
  )
  // Gates the column-mapping step's own submit — every `required` field
  // needs some column mapped to it before there's anything worth
  // previewing (a `"grouped"` shape's own required `group_key` comes from
  // `groupKeyColumn` instead of this table); the backend re-checks the
  // exact same thing (`service.parse_file`'s own `missing_required`),
  // this is purely so the button and the "still needed" strip reflect it
  // up front instead of round-tripping to find out.
  const claimedTargetKeys = new Set(Object.values(columnTargets).filter(Boolean))
  const missingRequiredFields = [
    ...(groupKeyField && !groupKeyColumn ? [groupKeyField] : []),
    ...tableFields.filter((f) => f.required && !claimedTargetKeys.has(f.key)),
  ]
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
    const result = data as unknown as ColumnsResult
    setColumns(result)
    setShape(result.shape)
    setGroupKeyColumn(result.shape.group_key_column ?? '')
    setColumnTargets({})
    setColumnKinds({})
    setStep('columns')
  }

  // The Shape panel's own change handler (IMPORT_WIZARD.md §7 Phase 4
  // item 1) — 100% client-side, no re-parse (`ColumnsResult`'s own
  // comment). Always resets every mapping-table choice made so far,
  // including the dedicated group-key picker: the valid target-key set
  // changes underneath them the moment `rows_per_entry`/`amount_style`
  // changes, so a mapping made against the old shape isn't safe to keep.
  function handleShapeChange(patch: Partial<Shape>) {
    setShape((s) => ({ ...s, ...patch }))
    setGroupKeyColumn('')
    setColumnTargets({})
    setColumnKinds({})
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
    if (columnsChanged) {
      setColumnTargets({})
      setColumnKinds({})
      setGroupKeyColumn('')
    }
  }

  function handleColumnsSubmit(e: FormEvent) {
    e.preventDefault()
    if (!columns || missingRequiredFields.length || duplicateTargetClaims.length) return
    // Invert column->target into the wire's target->column shape. Safe
    // to do with a plain assignment (rather than guarding each write)
    // because the button above is already disabled while
    // `duplicateTargetClaims` is non-empty — nothing here silently drops
    // a second claim on the same key without the user having already
    // been shown which columns clash.
    const column_map: Record<string, string> = {}
    const column_kinds: Record<string, string> = {}
    for (const [col, target] of Object.entries(columnTargets)) {
      if (!target) continue
      column_map[target] = col
      const field = tableFields.find((f) => f.key === target)
      if (field?.lookup_capable) column_kinds[target] = columnKinds[col] ?? defaultColumnKind(target, shape)
    }
    if (shape.rows_per_entry === 'grouped' && groupKeyColumn) column_map.group_key = groupKeyColumn
    void submitColumns(column_map, column_kinds)
  }

  async function submitColumns(column_map: Record<string, string>, column_kinds: Record<string, string>) {
    if (!columns) return
    setPreviewing(true)
    setFlash(null)
    const { data, error } = await client.POST('/import/mapped/preview', {
      body: {
        filename: columns.filename, target_scenario_id: columns.target_scenario_id,
        file_content_b64: columns.file_content_b64, shape: shape as unknown as WireShape,
        column_map, column_kinds, dialect: columns.dialect as unknown as WireDialect,
      },
    })
    setPreviewing(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not read that file with this mapping') })
      return
    }
    setPreview(data as unknown as PreviewResult)
    setValueMaps({})
    setFlipSign(false)
    setStep('review')
  }

  // The review step's own Confirm (IMPORT_WIZARD.md §3 step 5, §7 Phase
  // 3) — runs the real transform against the value maps just chosen, but
  // *without* staging anything yet (`POST /import/mapped/validate`, pure
  // — no database). A clean file (no row errors) skips straight to
  // `commit()`, same as this step always did; a file with any row errors
  // shows the new validation-report step instead, so staging the rest
  // and skipping those rows is something the user chooses, not the old
  // implicit default.
  async function handleReviewSubmit(e: FormEvent) {
    e.preventDefault()
    if (!preview) return
    setValidating(true)
    setFlash(null)
    const { data, error } = await client.POST('/import/mapped/validate', {
      body: {
        filename: preview.filename,
        target_scenario_id: preview.target_scenario_id,
        file_content_b64: preview.file_content_b64,
        shape: preview.shape as unknown as WireShape,
        column_map: preview.column_map,
        column_kinds: preview.column_kinds,
        dialect: preview.dialect as unknown as WireDialect,
        value_maps: valueMaps,
        flip_sign: flipSign,
      },
    })
    setValidating(false)
    if (error) {
      setFlash({ err: errorDetail(error, 'Could not check those rows') })
      return
    }
    const result = data as unknown as ValidateResult
    if (!result.errors.length) {
      await commit(result, false)
      return
    }
    setValidation(result)
    setStep('validate')
  }

  // The actual commit, `POST /import/mapped` — shared by the clean-file
  // path above (called straight from `handleReviewSubmit`, `skipBadRows:
  // false` since there's nothing to skip) and the validation-report
  // step's own "stage the rest" button (`skipBadRows: true`, an explicit
  // confirmation the backend requires whenever row errors exist —
  // `service.import_file`'s own docstring).
  async function commit(payload: ValidateResult, skipBadRows: boolean) {
    setCommitting(true)
    const { data, error } = await client.POST('/import/mapped', {
      body: {
        filename: payload.filename,
        target_scenario_id: payload.target_scenario_id,
        file_content_b64: payload.file_content_b64,
        shape: payload.shape as unknown as WireShape,
        column_map: payload.column_map,
        column_kinds: payload.column_kinds,
        dialect: payload.dialect as unknown as WireDialect,
        value_maps: payload.value_maps,
        flip_sign: payload.flip_sign,
        skip_bad_rows: skipBadRows,
      },
    })
    setCommitting(false)
    if (error) {
      // Stays on whichever step is currently shown (review or the
      // validation report) rather than bouncing back to upload — the
      // mappings are still right here in component state, there's no
      // server-side state between any of these steps to restore from
      // either way.
      setFlash({ err: errorDetail(error, 'Could not stage those rows') })
      return
    }
    const result = data as unknown as { staged_count: number; errors: RowError[] }
    const okMsg = `Staged ${result.staged_count} entr${result.staged_count === 1 ? 'y' : 'ies'} for review in Staging`
    setFlash({ ok: okMsg, err: result.errors.length ? skippedRowsMessage(result.errors) : undefined })
    setFile(null)
    setColumns(null)
    setPreview(null)
    setValidation(null)
    setStep('upload')
    onStaged()
  }

  function startOver() {
    setFile(null)
    setColumns(null)
    setColumnTargets({})
    setColumnKinds({})
    setGroupKeyColumn('')
    setPreview(null)
    setValidation(null)
    setFlash(null)
    setStep('upload')
  }

  return (
    <>
      {step === 'upload' && (
        <>
          <p className="page-sub">
            Works with any CSV shape — one row per transaction or grouped rows sharing an entry number, a single
            signed Amount column or separate Debit/Credit columns. Map this file's own columns onto whichever
            fields match in the next step, and every entry gets turned into a proper balanced double-entry
            posting, staged in <Link className="quiet-link" to="/app/staging">Staging</Link> for review same as
            any other import.
          </p>

          {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

          <div className="panel">
            <h2>Upload a CSV</h2>
            <p className="dim small">
              Whatever columns and shape your file already has — the next step guesses, then lets you map it
              exactly onto what this importer needs.
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

          {/* The Shape panel (IMPORT_WIZARD.md §7 Phase 4 item 1) —
              sniffed on upload, editable here, 100% client-side (no
              re-parse needed, see `handleShapeChange`'s own comment).
              Lives inside the columns step, same "no separate wizard
              step" precedent the Dialect panel already established.
              Above Dialect: shape decides which target fields exist at
              all, dialect decides how a mapped column's own cells split
              — shape has to be settled first for the mapping table below
              to make sense. */}
          <div className="panel">
            <h2>Shape</h2>
            <p className="dim small">
              Guessed from the file itself — usually right, always editable. Changing either of these resets the
              mapping table below, since which fields exist depends on it.
            </p>
            <div className="grid-form">
              <label className="field">
                Rows per entry
                <Combobox
                  options={ROWS_PER_ENTRY_OPTIONS}
                  value={shape.rows_per_entry}
                  onChange={(v) => handleShapeChange({ rows_per_entry: v })}
                />
              </label>
              {shape.rows_per_entry === 'grouped' && (
                <label className="field">
                  Which column identifies each entry
                  <Combobox
                    options={[CHOOSE, ...columns.columns.map((c) => ({ value: c, label: c }))]}
                    value={groupKeyColumn}
                    onChange={setGroupKeyColumn}
                  />
                </label>
              )}
              <label className="field">
                Amount
                <Combobox
                  options={AMOUNT_STYLE_OPTIONS}
                  value={shape.amount_style}
                  onChange={(v) => handleShapeChange({ amount_style: v })}
                />
              </label>
            </div>
          </div>

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
                  silently dropping whatever a user never picked. A row
                  whose chosen target is `lookup_capable` (account/
                  category) grows a second control (IMPORT_WIZARD.md §7
                  Phase 4 item 2) — does this column already hold a real
                  account code, or a label that needs mapping to one in
                  the review step. */}
              <div style={{ overflowX: 'auto' }}>
                <table className="ledger">
                  <thead>
                    <tr><th>Import file column</th><th>Sample value</th><th>Target data field</th><th>Holds</th></tr>
                  </thead>
                  <tbody>
                    {columns.columns.map((c) => {
                      const target = columnTargets[c] ?? ''
                      const field = tableFields.find((f) => f.key === target)
                      return (
                        <tr key={c}>
                          <td className="mono">{c}</td>
                          <td className="dim">
                            {columns.sample_rows.slice(0, 3).map((r) => r[c] || '—').join(', ')}
                          </td>
                          <td>
                            <Combobox
                              options={targetOptions}
                              value={target}
                              onChange={(v) => setColumnTargets((m) => ({ ...m, [c]: v }))}
                            />
                          </td>
                          <td>
                            {field?.lookup_capable && (
                              <Combobox
                                options={COLUMN_KIND_OPTIONS}
                                value={columnKinds[c] ?? defaultColumnKind(target, shape)}
                                onChange={(v) => setColumnKinds((m) => ({ ...m, [c]: v as 'code' | 'label' }))}
                              />
                            )}
                          </td>
                        </tr>
                      )
                    })}
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
                  {tableFields.find((f) => f.key === target)?.label ?? target} — pick one.
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
            value below to a real PostWarden account, then Stage — every entry becomes one balanced double-entry
            posting in <Link className="quiet-link" to="/app/staging">Staging</Link>. Leave a value unmapped to
            skip every row that uses it (reported, not silently dropped).
          </p>

          {flash?.ok && <div className="flash flash-ok">{flash.ok}</div>}
          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

          <form onSubmit={handleReviewSubmit}>
            {/* One lookup table per `values_found` key (IMPORT_WIZARD.md
                §7 Phase 4 item 2) — a fully `"code"`-kind mapping (e.g.
                the old plain importer's own Export-CSV shape) comes back
                with an empty `values_found` and renders zero tables here,
                same immediacy that importer always had. */}
            {Object.entries(preview.values_found).map(([key, vf]) => {
              const field = columns?.fields_by_shape[shapeKey(preview.shape)]?.find((f) => f.key === key)
              const label = field?.label ?? key
              const blankLabel = key === 'category' ? '(no category)' : '(blank)'
              const heading = key === 'account' ? `${label} — which is the money side?`
                : key === 'category' ? `${label} — which account is the other side?`
                : `${label} — which account?`
              return (
                <div className="panel" key={key}>
                  <h2>{heading}</h2>
                  {key === 'category' && (
                    <p className="dim small">
                      &quot;(no category)&quot; covers transfers/withdrawals and anything else this export left
                      blank — map it to whichever single account fits most of those rows, or leave it unmapped to
                      skip them all.
                    </p>
                  )}
                  <table className="ledger">
                    <thead><tr><th>Found in file</th><th>Maps to</th></tr></thead>
                    <tbody>
                      {vf.has_blank_rows && (
                        <tr>
                          <td className="dim italic">{blankLabel}</td>
                          <td>
                            <Combobox
                              options={accountOptions}
                              value={valueMaps[key]?.[''] ?? ''}
                              onChange={(v) => setValueMaps((m) => ({ ...m, [key]: { ...m[key], '': v } }))}
                            />
                          </td>
                        </tr>
                      )}
                      {vf.distinct.map((val) => (
                        <tr key={val}>
                          <td className="mono">{val}</td>
                          <td>
                            <Combobox
                              options={accountOptions}
                              value={valueMaps[key]?.[val] ?? ''}
                              onChange={(v) => setValueMaps((m) => ({ ...m, [key]: { ...m[key], [val]: v } }))}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })}

            <div className="panel">
              {/* No signed value exists to flip once the file's own two
                  Debit/Credit columns already carry it (IMPORT_WIZARD.md
                  §7 Phase 4) — hidden outright, not just disabled. */}
              {preview.shape.amount_style !== 'debit_credit' && (
                <label className="checkline">
                  <input type="checkbox" checked={flipSign} onChange={(e) => setFlipSign(e.target.checked)} />
                  Flip Amount&apos;s sign (check this if a normal expense shows as a positive number in your file
                  instead of negative)
                </label>
              )}
              <button type="submit" disabled={validating || committing} style={{ marginTop: '0.8rem' }}>
                {validating ? 'Checking…'
                  : committing ? 'Staging…'
                  : `Stage ${preview.row_count} row${preview.row_count === 1 ? '' : 's'}`}
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

      {step === 'validate' && validation && (
        <>
          {/* The validation-report step (IMPORT_WIZARD.md §3 step 5, §7
              Phase 3) — only ever shown once `POST /import/mapped/
              validate` comes back with at least one row error (R1: a
              clean file never sees this screen at all, `handleReviewSubmit`
              stages it directly). Every failing row, its own mapped
              values, and why it failed — not the old flat joined-string
              banner — with an explicit choice: fix the mapping and
              re-check, or stage the rest and skip these. Columns are
              whatever the current shape's own target fields are (`columns.
              fields_by_shape`), not a fixed Date/Account/Category/Amount/
              Payee list — a grouped or Debit/Credit shape's own rows carry
              different fields entirely. */}
          <p className="page-sub">
            {validation.errors.length} row{validation.errors.length === 1 ? '' : 's'} can&apos;t be staged as
            currently mapped; {validation.groups_count} other{validation.groups_count === 1 ? '' : 's'} would
            stage fine. Fix the mapping and go back, or stage the rest and skip these.
          </p>

          {flash?.err && <div className="flash flash-err">{flash.err}</div>}

          <div className="panel">
            <h2>Rows that didn&apos;t pass validation</h2>
            <div style={{ overflowX: 'auto' }}>
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Row</th>
                    {(columns?.fields_by_shape[shapeKey(validation.shape)] ?? []).map((f) => (
                      <th key={f.key}>{f.label}</th>
                    ))}
                    <th>Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.errors.slice(0, IMPORT_MAX_ERRORS_SHOWN).map((e) => (
                    <tr key={e.row_no}>
                      <td className="mono">{e.row_no}</td>
                      {(columns?.fields_by_shape[shapeKey(validation.shape)] ?? []).map((f) => (
                        <td className="mono" key={f.key}>{e.raw[f.key] || '—'}</td>
                      ))}
                      <td>{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {validation.errors.length > IMPORT_MAX_ERRORS_SHOWN && (
              <p className="dim small" style={{ marginTop: '0.5rem' }}>
                ...and {validation.errors.length - IMPORT_MAX_ERRORS_SHOWN} more.
              </p>
            )}

            <button type="button" disabled={committing || !validation.groups_count}
                    onClick={() => commit(validation, true)} style={{ marginTop: '0.8rem' }}>
              {committing ? 'Staging…'
                : `Stage ${validation.groups_count} row${validation.groups_count === 1 ? '' : 's'}, `
                  + `skip ${validation.errors.length}`}
            </button>
            <button type="button" className="quiet" style={{ marginLeft: '0.5rem' }}
                    onClick={() => { setValidation(null); setStep('review') }}>
              Back to review
            </button>
            <button type="button" className="quiet" style={{ marginLeft: '0.5rem' }} onClick={startOver}>
              Start over
            </button>
          </div>
        </>
      )}
    </>
  )
}
