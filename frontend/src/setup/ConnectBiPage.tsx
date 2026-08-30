import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import client from '../api/client'

// Ported from app/templates/connect_bi.html (Phase 4.7) — no new backend
// work at all, unlike this same phase's own dashboard: `GET /settings/
// connect-bi` and `GET /settings/connect-bi/download.pbids` were already
// built in `analytics/router.py` back in Phase 1.14, alongside the `/api/*`
// JSON mirror (see that module's own docstring for why Connect BI lives
// there rather than a dedicated module). `setup/SettingsPage.tsx`'s own
// comment claiming this needed "real backend work of its own (Phase 4.7)"
// was simply wrong — written before anyone had reason to check
// `analytics/` — corrected in the same commit as this file.
//
// `GET /settings/connect-bi`'s own response is a plain `dict` (no
// Pydantic model, same as every report route), so this casts through a
// local interface, same gap every report screen's own comment documents.
interface ConnectBiInfo {
  bi_host: string
  bi_port: string
  bi_db: string
  bi_user: string
  bi_objects: [string, string][]
}

export default function ConnectBiPage() {
  const [info, setInfo] = useState<ConnectBiInfo | null>(null)

  useEffect(() => {
    let cancelled = false
    client.GET('/settings/connect-bi').then(({ data }) => {
      if (!cancelled && data) setInfo(data as unknown as ConnectBiInfo)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!info) return <p>Loading…</p>

  return (
    <>
      <p className="page-sub"><Link className="quiet-link" to="/app/settings">← Back to Settings</Link></p>

      <div className="panel">
        <h2>Connection</h2>
        <p className="dim small" style={{ marginTop: 0 }}>
          Power BI, Excel, and psql can all connect straight to this database — no export step. In
          Power BI Desktop: Get Data → PostgreSQL database, or open the downloaded file below to
          skip typing these in.
        </p>
        <table className="ledger">
          <tbody>
            <tr><th>Server</th><td className="mono">{info.bi_host}:{info.bi_port}</td></tr>
            <tr><th>Database</th><td className="mono">{info.bi_db}</td></tr>
            <tr><th>Username</th><td className="mono">{info.bi_user}</td></tr>
            <tr><th>Password</th><td className="mono">{info.bi_user}</td></tr>
          </tbody>
        </table>
        <p className="dim small" style={{ marginBottom: 0 }}>
          <a href="/settings/connect-bi/download.pbids" className="button-link">
            Download .pbids for Power BI Desktop
          </a>
        </p>
      </div>

      <div className="panel">
        <h2>What&apos;s exposed</h2>
        <p className="dim small" style={{ marginTop: 0 }}>
          <span className="mono">{info.bi_user}</span> is read-only and can <span className="mono">SELECT</span>{' '}
          only the reporting views/function below — never a base table like{' '}
          <span className="mono">journal_lines</span> or <span className="mono">users</span>, so this login
          can&apos;t post an entry, edit history, or read a password hash, no matter what connects with it.
        </p>
        <table className="ledger">
          <thead><tr><th>Object</th><th>What it is</th></tr></thead>
          <tbody>
            {info.bi_objects.map(([name, desc]) => (
              <tr key={name}>
                <td className="mono">{name}</td>
                <td>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Connecting from outside this machine</h2>
        <p className="dim small" style={{ marginTop: 0, marginBottom: 0 }}>
          By default Postgres only accepts connections from this machine itself — that&apos;s what keeps{' '}
          <span className="mono">{info.bi_user}</span>&apos;s fixed password safe even though it&apos;s the
          same for every install. Reaching it from another machine (a GCP-deployed instance, say) needs a
          tunnel first — see &quot;Connecting Power BI / Excel&quot; in{' '}
          <a href="https://github.com/PostWardenLabs/PostWarden/blob/master/deploy/gcp/README.md"
             target="_blank" rel="noopener">deploy/gcp/README.md</a>. If you do widen Postgres&apos;s own
          port beyond localhost, change this password first —{' '}
          <span className="mono">ALTER ROLE {info.bi_user} WITH PASSWORD &apos;something-only-you-know&apos;;</span>{' '}
          in <span className="mono">psql</span> — the same way the README already tells you to change the
          app&apos;s own <span className="mono">postwarden</span>/<span className="mono">postwarden</span> login
          before doing that.
        </p>
      </div>
    </>
  )
}
