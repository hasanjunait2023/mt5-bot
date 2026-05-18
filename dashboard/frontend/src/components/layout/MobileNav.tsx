import { NavLink } from 'react-router-dom'
import clsx from 'clsx'

const NAV = [
  { to: '/',        label: 'Overview', icon: '⬛' },
  { to: '/positions', label: 'Trades',  icon: '📊' },
  { to: '/eas',       label: 'EAs',    icon: '🤖' },
  { to: '/bots',      label: 'Bots',   icon: '🧠' },
  { to: '/logs',      label: 'Logs',   icon: '📄' },
  { to: '/reports',   label: 'Reports',icon: '📈' },
]

export function MobileNav() {
  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 bg-bg-surface border-t border-border flex z-50">
      {NAV.map(({ to, label, icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            clsx(
              'flex-1 flex flex-col items-center justify-center gap-0.5 text-xs transition-colors',
              isActive ? 'text-accent' : 'text-text-secondary'
            )
          }
        >
          <span className="text-lg leading-none">{icon}</span>
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
