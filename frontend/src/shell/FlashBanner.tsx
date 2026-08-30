import { useState } from 'react'

interface FlashState {
  ok: string | null
  err: string | null
}

function readFlashFromLocation(): FlashState {
  const params = new URLSearchParams(window.location.search)
  return { ok: params.get('ok'), err: params.get('err') }
}

// Ported from base.html's own
// `{% if request.query_params.get('ok') or ok %}` blocks — reads the
// same ?ok=/?err= query-string convention every legacy redirect-after-
// write already uses. Legacy also accepted `ok`/`err` as a route's own
// template context (a page setting one directly, with no redirect
// involved) — no frontend screen does that yet, so only the query-string
// half is ported here; a `flash` prop can be added once a real
// write-without-redirect flow exists to need it.
//
// Reads `window.location.search` via useState's lazy initializer, once,
// at mount — not in an effect (a plain redirect already gives this
// component a fresh mount with the new query string, so there is nothing
// ongoing to synchronize with yet; that becomes an effect's job once a
// client-side router can re-render this same mounted instance across a
// navigation).
export default function FlashBanner() {
  const [flash] = useState<FlashState>(readFlashFromLocation)

  return (
    <>
      {flash.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash.err && <div className="flash flash-err">{flash.err}</div>}
    </>
  )
}
