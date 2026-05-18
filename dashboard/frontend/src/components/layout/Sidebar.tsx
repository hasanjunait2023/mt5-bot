import { NavLink } from 'react-router-dom'
import clsx from 'clsx'

const NAV = [
  { to: '/',        label: 'Overview',    icon: '⬛' },
  { to: '/positions', label: 'Positions',  icon: '📊' },
  { to: '/history',   label: 'History',   icon: '📋' },
  { to: '/bots',      label: 'Bots & Agents', icon: '🤖' },
  { to: '/reports',   label: 'Reports',   icon: '📈' },
  { to: '/logs',      label: 'Logs',      icon: '📄' },
  { to: '/eas',        label: 'Expert Advisors', icon: '🤖' },
  { to: '/settings',  label: 'Settings',  icon: '⚙️' },
]

export function Sidebar() {
  return (
    <aside className="hidden md:flex flex-col w-[220px] bg-bg-surface border-r border-border shrink-0">
      <nav className="flex-1 pt-2">
        {NAV.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors',
                isActive
                  ? 'text-text-primary bg-bg-elevated border-l-2 border-accent'
                  : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated border-l-2 border-transparent'
              )
            }
          >
            <span className="text-base leading-none">{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-border">
        <p className="text-text-muted text-xs">MT5 Bot Monitor v1.0</p>
      </div>
    </aside>
  )
}
