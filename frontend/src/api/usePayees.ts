import { useEffect, useState } from 'react'

import client from './client'

// GET /payees's own response is a plain `list[dict]`
// (`modules/reference/repository.py`'s own `payees_all`), same
// cast-through-a-local-interface gap every other reference hook already
// documents. Used by the Journal's own Payee picker; `entry_count`
// (`payees_all`'s own subquery) is real but unused here.
export interface Payee {
  id: number
  name: string
  is_active: boolean
}

export function usePayees(): Payee[] | null {
  const [payees, setPayees] = useState<Payee[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/payees').then(({ data }) => {
      if (!cancelled && data) setPayees(data as unknown as Payee[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return payees
}
