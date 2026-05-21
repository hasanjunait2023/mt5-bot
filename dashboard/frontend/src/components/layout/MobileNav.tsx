import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { Icon, type IconName } from '../ui/Icon'

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/',          label: 'Overview', icon: 'overview' },
  { to: '/positions', label: 'Trades',   icon: 'positions' },
  { to: '/eas',       label: 'EAs',      icon: 'eas' },
  { to: '/cpp',       label: 'CPP',      icon: 'reports' },
  { to: '/bots',      label: 'Bots',     icon: 'bots' },
  { to: '/logs',      label: 'Logs',     icon: 'logs' },
  { to: '/reports',   label: 'Reports',  icon: 'reports' },
]

export function MobileNav() {
  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 z-50
                    bg-bg-surface/80 backdrop-blur-xl border-t border-border flex">
      {NAV.map(({ to, label, icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            clsx(
              'relative flex-1 flex flex-col items-center justify-center gap-1 text-[11px] transition-colors',
              isActive ? 'text-accent' : 'text-text-muted'
            )
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <span className="absolute top-0 w-8 h-[3px] rounded-full bg-accent shadow-glow-accent" />
              )}
              <Icon name={icon} size={20} />
              <span className="font-medium">{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
