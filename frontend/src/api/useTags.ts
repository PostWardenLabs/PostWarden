import { useEffect, useState } from 'react'

import client from './client'

// GET /tags's own response — same shape `tags/TagsPage.tsx` (Phase 3.2)
// already fetches inline for its own CRUD state, but factored out here
// as a plain one-shot hook (matching `useScenarios.ts`/`useAccounts.ts`)
// for a caller that only wants the *list*, not the full add/rename/
// archive/merge machinery — the Journal's `TagInput.tsx` (Phase 3.4)
// needs suggestions to autocomplete against, nothing more. TagsPage.tsx
// itself is deliberately left alone rather than retrofitted onto this:
// it reloads after every one of its own mutations, which this hook's
// plain fetch-on-mount shape doesn't (and shouldn't) provide.
export interface TagOption {
  id: number
  name: string
  is_active: boolean
}

export function useTags(): TagOption[] | null {
  const [tags, setTags] = useState<TagOption[] | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/tags').then(({ data }) => {
      if (!cancelled && data) setTags(data as unknown as TagOption[])
    })
    return () => {
      cancelled = true
    }
  }, [])

  return tags
}
