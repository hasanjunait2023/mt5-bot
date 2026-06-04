import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { Icon } from '../ui/Icon'
import { NAV, MOBILE_PRIMARY } from './navItems'

const primary = MOBILE_PRIMARY
  .map(to => NAV.find(n => n.to === to))
  .filter((n): n is (typeof NAV)[number] => Boolean(n))

export function MobileNav() {
  const [open, setOpen] = useState(false)

  return (
    <>
      {/* Full-page sheet listing every route — reached via the "More" tab so no
          page is unreachable on mobile (the desktop sidebar is hidden here). */}
      {open && (
        <div
          className="md:hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            className="absolute bottom-16 left-0 right-0 max-h-[70vh] overflow-y-auto
                       bg-bg-surface/95 backdrop-blur-xl border-t border-border
                       p-3 grid grid-cols-3 gap-2"
            onClick={e => e.stopPropagation()}
          >
            {NAV.map(({ to, label, icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  clsx(
                    'flex flex-col items-center justify-center gap-1.5 h-20 rounded-lg text-[11px] text-center px-1 transition-colors',
                    isActive
                      ? 'text-accent bg-white/[0.05] ring-1 ring-border'
                      : 'text-text-secondary bg-white/[0.02]'
                  )
                }
              >
                <Icon name={icon} size={20} />
                <span className="font-medium leading-tight">{label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      )}

      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 z-50
                      bg-bg-surface/80 backdrop-blur-xl border-t border-border flex">
        {primary.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={() => setOpen(false)}
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
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className={clsx(
            'relative flex-1 flex flex-col items-center justify-center gap-1 text-[11px] transition-colors',
            open ? 'text-accent' : 'text-text-muted'
          )}
        >
          {open && <span className="absolute top-0 w-8 h-[3px] rounded-full bg-accent shadow-glow-accent" />}
          <Icon name="system" size={20} />
          <span className="font-medium">More</span>
        </button>
      </nav>
    </>
  )
}
