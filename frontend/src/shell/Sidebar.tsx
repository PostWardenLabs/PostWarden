import { Link } from 'react-router-dom'

import type { NavGroup, NavLink } from './nav'
import { NAV_GROUPS } from './nav'
import { useSidebarGroupCollapse } from './useSidebarGroupCollapse'

// A real client-side <Link> for a link whose screen actually exists as a
// route (Phase 3.2 on: `nav.ts`'s own `client: true` flag), a plain
// `<a href>` full-page navigation for everything else — see nav.ts's own
// comment on `NavLink.client` for why the two still coexist here instead
// of every link moving over at once.
function NavAnchor({ link, active }: { link: NavLink; active: boolean }) {
  const className = active ? 'active' : undefined
  if (link.client) {
    return (
      <Link to={link.href} className={className}>
        {link.label}
      </Link>
    )
  }
  return (
    <a href={link.href} className={className}>
      {link.label}
    </a>
  )
}

interface SidebarGroupProps {
  group: NavGroup
  current?: string
}

// A real <button>, not a styled <div> — see index.css's own
// .sidebar-label comment for why (keyboard reachability, matching
// sidebar-collapse.js's original element choice). The chevron rotates via
// the shared .chevron classes (also ported this phase); .collapsed on the
// wrapping group is what index.css hooks both the chevron rotation and
// the `display: none` on every sibling <a> off of.
function SidebarGroup({ group, current }: SidebarGroupProps) {
  const { collapsed, toggle } = useSidebarGroupCollapse(group.key)
  return (
    <div className={collapsed ? 'sidebar-group collapsed' : 'sidebar-group'} data-sidebar-key={group.key}>
      <button type="button" className="sidebar-label" aria-expanded={!collapsed} onClick={toggle}>
        {group.label}
        <span className="chevron chevron-down sidebar-chevron" />
      </button>
      {group.links.map((link) => (
        <NavAnchor key={link.key} link={link} active={link.key === current} />
      ))}
    </div>
  )
}

interface SidebarProps {
  current?: string
  open: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
}

// Ported from base.html's <nav id="sidebar">. Hover/pin mechanics live in
// Shell.tsx (useSidebarPin) and are only passed in here as plain
// open/onMouseEnter/onMouseLeave props — this component owns the nav
// structure and the per-group collapse state, nothing about whether it's
// currently visible.
export default function Sidebar({ current, open, onMouseEnter, onMouseLeave }: SidebarProps) {
  return (
    <nav
      id="sidebar"
      className={open ? 'sidebar open' : 'sidebar'}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="sidebar-group">
        <Link to="/" className={current === 'dashboard' ? 'active' : undefined}>
          Dashboard
        </Link>
      </div>
      {NAV_GROUPS.map((group) => (
        <SidebarGroup key={group.key} group={group} current={current} />
      ))}
    </nav>
  )
}
