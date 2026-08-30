import { useRef, useState } from 'react'

// Ported from app/static/import-file.js (Phase 4.7) — the CSV upload
// button + chosen-filename box shared by Import and Import-with-rules
// (this widget's first two callers). Legacy's version keeps a real
// `<input type="file">` in the DOM (`.sr-only`, not `display: none`, so
// it stays keyboard/label-operable) and syncs a visible button + name
// box to it by hand; this component *is* that input, plus the two
// visible pieces, as one controlled unit — `onFileChange` is how a
// parent form learns which `File` was actually picked, since there's no
// native form submission here to read `event.target.files` from at
// submit time (both callers build a `FormData` themselves and post it
// via the typed client).
//
// `id`/`name` are passed through mostly so a `<label htmlFor=...>` next
// to this component still works the same way legacy's own `<label
// for="import-file-input">` did — clicking the label's text focuses/
// activates the real input with no JS needed, same as before; the
// visible "Choose file" button covers the one case a label's own click
// doesn't reach (a button nested inside the label wouldn't get the
// label's forwarded click either, same reasoning import-file.js's own
// comment already gives).
interface FileFieldProps {
  id: string
  name: string
  accept?: string
  required?: boolean
  onFileChange: (file: File | null) => void
}

export default function FileField({ id, name, accept, required, onFileChange }: FileFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)

  return (
    <span className="file-field">
      <button type="button" onClick={() => inputRef.current?.click()}>Choose file</button>
      <span className={fileName ? 'file-field-name' : 'file-field-name dim'}>
        {fileName ?? 'No file chosen'}
      </span>
      <input
        ref={inputRef}
        type="file"
        id={id}
        name={name}
        accept={accept}
        required={required}
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null
          setFileName(file?.name ?? null)
          onFileChange(file)
        }}
      />
    </span>
  )
}
