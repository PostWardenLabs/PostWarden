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
// `user` is null until Phase 3.1 (login) gives the app real session
// state — same "don't reach into a mechanism that doesn't exist yet"
// reasoning every backend module already applied to auth/CSRF ahead of
// Phase 1.11. Matches legacy exactly: no sidebar, no topbar user area,
// with nobody logged in — only the topbar's left half, the flash slot,
// and the footer render.
//
// No footer version number yet (legacy's own "PostWarden v{{ version }}"
// reads the repo-root VERSION file at template-render time) — no backend
// route exposes it anywhere the frontend can reach yet. A one-line gap,
// deliberately not closed here: it doesn't belong to this phase's own
// scope (sidebar/topbar/flash/pre-paint script, per REBUILD_STATUS.md),
// and the obvious real fix (piggyback it on a route that already needs
// to exist, e.g. Phase 3.1's own GET /me) doesn't exist yet either.
export default function Shell({ title, current, user, onLogout, children }: ShellProps) {
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
      <footer className="footer">PostWarden</footer>
    </>
  )
}
