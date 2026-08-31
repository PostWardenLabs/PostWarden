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

// .topbar-inner is deliberately NOT sized off --content-max — see
// index.css's own comment on that.
//
// The wordmark is a React Router `<Link>`, not a plain `<a href="/">` —
// "/" is a real client route (App.tsx's own Dashboard), so clicking it
// re-renders in place rather than forcing a full page reload. The
// username link is the same kind of `<Link>` — `current` can be either
// `'settings'` or `'settings_account'` (App.tsx's own `routeKey`, one
// nav key per real route, the account sub-page split out as its own
// route), so the active check matches either with `startsWith` rather
// than gaining a second exact comparison.
//
// The username link and "Log out" button only render with a real
// `user`. Logout is a plain <button>, not a `<form method="post">` — a
// real form submit would be a full-page navigation, wrong for a SPA;
// `onLogout` is wired to `session.logout` (App.tsx), which POSTs
// `/logout` with the current session's CSRF token.
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
              <Link
                to="/app/settings"
                className={
                  current?.startsWith('settings') ? 'username-link dim small active' : 'username-link dim small'
                }
              >
                {user.username}
              </Link>
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
