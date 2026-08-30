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
          <a className="wordmark" href="/">
            {title}
            <span className="wordmark-brand"> · PostWarden</span>
          </a>
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
