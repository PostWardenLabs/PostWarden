import { Link } from 'react-router-dom'

export interface TopbarUser {
  username: string
}

interface TopbarProps {
  title: string
  current?: string
  user: TopbarUser | null
  onLogout?: () => void
}

// Ported from base.html's <header class="topbar">. .topbar-inner is
// deliberately NOT sized off --content-max — see index.css's own comment
// on that, carried over unchanged with the rest of this section.
//
// The wordmark is a React Router `<Link>` as of Phase 3.2, not a plain
// `<a href="/">` — "/" is now a real client route (App.tsx's own
// Dashboard), so clicking it should re-render in place rather than force
// a full page reload. `/settings` stays a plain `<a>`: that screen isn't
// built yet, same "not this phase's job" reasoning nav.ts's own `client`
// flag comment gives for every other still-unbuilt sidebar link.
//
// The username link and "Log out" button only render with a real `user`
// — matching legacy's own `{% if request.state.user %}` guard around the
// entire topbar-right block. Logout is a plain <button>, not legacy's
// `<form method="post" action="/logout">` — a real form submit would be a
// full-page navigation, wrong for a SPA; `onLogout` is where Phase 3.1
// wires a real `client.POST('/logout', ...)` call instead. It's optional
// and unwired for now because that call needs an X-CSRF-Token sourced
// from a real session, and there is no session anywhere in the frontend
// yet (Phase 3.1's login screen is what creates one) — same "don't reach
// into a mechanism that doesn't exist yet" reasoning every backend module
// already applied to its own CSRF gap ahead of Phase 1.11.
export default function Topbar({ title, current, user, onLogout }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-left">
          <Link className="wordmark" to="/">
            {title}
            <span className="wordmark-brand"> · PostWarden</span>
          </Link>
        </div>
        <div className="topbar-right">
          {user && (
            <>
              <a
                href="/settings"
                className={
                  current === 'settings' ? 'username-link dim small active' : 'username-link dim small'
                }
              >
                {user.username}
              </a>
              <button type="button" className="quiet" onClick={onLogout}>
                Log out
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
