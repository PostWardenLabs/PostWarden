import { useState } from 'react'

interface FlashState {
  ok: string | null
  err: string | null
}

function readFlashFromLocation(): FlashState {
  const params = new URLSearchParams(window.location.search)
  return { ok: params.get('ok'), err: params.get('err') }
}

// Reads the `?ok=`/`?err=` query-string convention set by a redirect
// after a server-side write.
//
// Reads `window.location.search` via useState's lazy initializer, once,
// at mount — not in an effect. `Shell` (which renders this) sits above
// `<Routes>` in App.tsx, so client-side navigation never remounts it;
// this only ever reflects the query string the page was first loaded
// with.
export default function FlashBanner() {
  const [flash] = useState<FlashState>(readFlashFromLocation)

  return (
    <>
      {flash.ok && <div className="flash flash-ok">{flash.ok}</div>}
      {flash.err && <div className="flash flash-err">{flash.err}</div>}
    </>
  )
}
