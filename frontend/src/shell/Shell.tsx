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

// The app chrome: the hamburger sidebar (hover-preview + click-to-pin —
// see useSidebarPin.ts and Sidebar.tsx), the topbar, the ok=/err= flash
// banners, and the footer. The pre-paint theme/font/pinned-sidebar
// restore lives in frontend/index.html directly, ahead of anything React
// renders — see that file's own comment; nothing here re-does it.
//
// `user` is real session state from `auth/SessionProvider.tsx`, supplied
// by App.tsx. With nobody logged in, only the topbar's left half, the
// flash slot, and the footer render — no sidebar, no topbar user area.
//
// `version` is sourced from `GET /config` (`useAppConfig`) by whichever
// caller has it — optional, and rendered without the "v" prefix at all
// when absent, the same tolerant-degradation choice `main.py`'s own
// `/config` route already makes for a missing VERSION file (a blank
// string, not a 500).
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
