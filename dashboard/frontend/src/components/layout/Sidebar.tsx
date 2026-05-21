import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { Icon, type IconName } from '../ui/Icon'

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/',          label: 'Overview',        icon: 'overview' },
  { to: '/positions', label: 'Positions',       icon: 'positions' },
  { to: '/history',   label: 'History',         icon: 'history' },
  { to: '/bots',      label: 'Bots & Agents',   icon: 'bots' },
  { to: '/system',    label: 'System Agents',   icon: 'system' },
  { to: '/reports',   label: 'Reports',         icon: 'reports' },
  { to: '/logs',      label: 'Logs',            icon: 'logs' },
  { to: '/eas',       label: 'Expert Advisors', icon: 'eas' },
  { to: '/cpp',       label: 'CPP Portfolio',   icon: 'reports' },
  { to: '/jtcc',      label: 'JTCC Signals',     icon: 'bots' },
  { to: '/signals',   label: 'Signals',          icon: 'system' },
  { to: '/desk',      label: 'Alpha Desk',       icon: 'reports' },
  { to: '/iconic',    label: 'Iconic Trader',    icon: 'bots' },
  { to: '/journal',   label: 'Trade Journal',    icon: 'history' },
  { to: '/telegram',  label: 'Telegram HQ',     icon: 'telegram' },
  { to: '/settings',  label: 'Settings',        icon: 'settings' },
]

export function Sidebar() {
  return (
    <aside className="hidden md:flex flex-col w-[232px] shrink-0
                      bg-bg-surface/55 backdrop-blur-xl border-r border-border">
      <nav className="flex-1 px-3 pt-4 space-y-1">
        {NAV.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'group relative flex items-center gap-3 px-3 h-10 rounded-lg text-sm transition-all duration-200',
                isActive
                  ? 'text-text-primary bg-white/[0.05] ring-1 ring-border'
                  : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.03]'
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={clsx(
                    'absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full transition-all duration-200',
                    isActive
                      ? 'h-5 bg-accent shadow-glow-accent'
                      : 'h-0 bg-transparent'
                  )}
                />
                <Icon
                  name={icon}
                  className={clsx(
                    'shrink-0 transition-colors',
                    isActive ? 'text-accent' : 'text-text-muted group-hover:text-text-secondary'
                  )}
                />
                <span className="font-medium tracking-tight">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="m-3 p-3 rounded-lg bg-white/[0.025] ring-1 ring-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse2" />
          <p className="text-text-secondary text-[11px] font-medium">Monitor active</p>
        </div>
        <p className="text-text-muted text-[11px] mt-1">MT5 Bot · v1.0</p>
      </div>
    </aside>
  )
}
