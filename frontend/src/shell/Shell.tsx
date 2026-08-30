import type { ReactNode } from 'react'
import { useEffect } from 'react'

import FlashBanner from './FlashBanner'
import Sidebar from './Sidebar'
import Topbar, { type TopbarUser } from './Topbar'
import { useSidebarPin } from './useSidebarPin'

interface ShellProps {
  title: string
  current?: string
  user: TopbarUser | null
  onLogout?: () => void
  version?: string
  children: ReactNode
}

// The app chrome, ported from app/templates/base.html: the hamburger
// sidebar (hover-preview + click-to-pin — see useSidebarPin.ts and
// Sidebar.tsx, ported from sidebar.js/sidebar-collapse.js), the topbar,
// the ok=/err= flash banners, and the footer. The pre-paint theme/font/
// pinned-sidebar restore that used to be base.html's own inline <head>
// script now lives in frontend/index.html directly, ahead of anything
// React renders — see that file's own comment; nothing here re-does it.
//
// `user` is real session state as of Phase 3.1 (`auth/SessionProvider.tsx`)
// — App.tsx is the caller that supplies it now, no longer a hardcoded
// placeholder. Matches legacy exactly: no sidebar, no topbar user area,
// with nobody logged in — only the topbar's left half, the flash slot,
// and the footer render.
//
// `version` closes the one gap Phase 2.4's own version of this comment
// left open: legacy's footer reads the repo-root VERSION file directly
// at template-render time (`"PostWarden v{{ version }}"`); this is a
// plain prop instead, sourced from `GET /config` (`useAppConfig`,
// Phase 3.1) by whichever caller has it — optional, and rendered without
// the "v" prefix at all when absent, the same tolerant-degradation
// choice `main.py`'s own `/config` route already makes for a missing
// VERSION file (a blank string, not a 500).
export default function Shell({ title, current, user, onLogout, version, children }: ShellProps) {
  const { open, previewOpen, scheduleClose, toggle } = useSidebarPin()

  useEffect(() => {
    document.title = `${title} · PostWarden`
  }, [title])

  return (
    <>
      {user && (
        <>
          <button
            type="button"
            id="sidebar-toggle"
            className="sidebar-toggle"
            aria-label="Toggle menu"
            aria-expanded={open}
            onMouseEnter={previewOpen}
            onMouseLeave={scheduleClose}
            onClick={toggle}
          >
            <span></span>
            <span></span>
            <span></span>
          </button>
          <Sidebar current={current} open={open} onMouseEnter={previewOpen} onMouseLeave={scheduleClose} />
        </>
      )}
      <Topbar title={title} current={current} user={user} onLogout={onLogout} />
      <main>
        <FlashBanner />
        {children}
      </main>
      <footer className="footer">PostWarden{version ? ` v${version}` : ''}</footer>
    </>
  )
}
