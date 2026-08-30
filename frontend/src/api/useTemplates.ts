import { useEffect, useState } from 'react'

import client from './client'

// GET /templates's own response — ported from `templates_full()`, each
// template already nested with its own `lines`/`tags` server-side (see
// `modules/scheduling/service.py`'s own `list_templates` docstring
// contrasting this against the Journal/Staging's three-parallel-dicts
// precursor). First caller is the Journal's "Load template" picker
// (Phase 3.4, `entry_templates.js`'s own React port) — `payee_name` is
// real (`templates_all`'s own join) but unused here, since the picker
// only ever needs `payee_id` to drive the New entry form's own Payee
// field the same way loading a template does in legacy.
export interface TemplateLine {
  code: string
  debit: string | null
  credit: string | null
  memo: string | null
}

export interface Template {
  id: number
  name: string
  description: string
  reference: string | null
  payee_id: number | null
  lines: TemplateLine[]
  tags: string[]
}

export function useTemplates(): Template[] | null {
  const [templates, setTemplates] = useState<Template[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/templates').then(({ data }) => {
      if (!cancelled && data) setTemplates(data as unknown as Template[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return templates
}
