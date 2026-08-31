import { useEffect, useState } from 'react'

import client from '../api/client'

// One-shot count of whatever's currently pending in Staging — first
// caller is `ScheduledPage.tsx`'s own banner; the Dashboard's identical
// banner is the likely second. `GET /staging` has no bespoke count
// endpoint of its own — `modules/staging/service.py::list_pending` was
// never paginated — so this fetches the full unfiltered list and reads
// its length, same "don't add a route for a number the existing one
// already answers" call `usePayees.ts`/`useTags.ts` implicitly make for
// their own callers that only need a count or a name list out of a
// fuller row shape.
export function useStagingPendingCount(): number | null {
  const [count, setCount] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/staging').then(({ data }) => {
      if (!cancelled && data) setCount((data as unknown as { entries: unknown[] }).entries.length)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return count
}
