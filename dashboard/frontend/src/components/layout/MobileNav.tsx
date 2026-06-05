import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { Icon } from '../ui/Icon'
import { NAV_GROUPS, navByPath, MOBILE_PRIMARY, type NavItem } from './navItems'
import { useFavorites } from '../../hooks/useFavorites'

export function MobileNav() {
  const [open, setOpen] = useState(false)
  const { favorites, isFavorite, toggle } = useFavorites()

  // Bottom tabs = the user's first 4 pinned favourites, else sensible defaults.
  const source = favorites.length ? favorites : MOBILE_PRIMARY
  const primary = source
    .map(navByPath)
    .filter((n): n is NavItem => Boolean(n))
    .slice(0, 4)

  return (
    <>
      {/* Full-page sheet — every route, grouped, each pinnable. Reached via the
          "More" tab so no page is unreachable on mobile. */}
      {open && (
        <div
          className="md:hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            className="absolute bottom-16 left-0 right-0 max-h-[74vh] overflow-y-auto
                       bg-bg-surface/95 backdrop-blur-2xl border-t border-border
                       rounded-t-2xl px-3 pt-3 pb-4 shadow-topbar"
            onClick={e => e.stopPropagation()}
          >
            <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-tint/15" />
            {NAV_GROUPS.map(group => (
              <div key={group.label} className="mb-3 last:mb-0">
                <p className="px-1 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-text-muted/80">
                  {group.label}
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {group.items.map(item => (
                    <SheetTile
                      key={item.to}
                      item={item}
                      pinned={isFavorite(item.to)}
                      onNavigate={() => setOpen(false)}
                      onToggle={() => toggle(item.to)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 z-50
                      bg-bg-surface/85 backdrop-blur-2xl border-t border-border flex
                      pb-[env(safe-area-inset-bottom)]">
        {primary.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={() => setOpen(false)}
            className={({ isActive }) =>
              clsx(
                'relative flex-1 flex flex-col items-center justify-center gap-1 text-[10.5px] transition-colors',
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
                <span className="font-medium truncate max-w-[64px]">{label}</span>
              </>
            )}
          </NavLink>
        ))}
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className={clsx(
            'relative flex-1 flex flex-col items-center justify-center gap-1 text-[10.5px] transition-colors',
            open ? 'text-accent' : 'text-text-muted'
          )}
        >
          {open && <span className="absolute top-0 w-8 h-[3px] rounded-full bg-accent shadow-glow-accent" />}
          <Icon name="hub" size={20} />
          <span className="font-medium">More</span>
        </button>
      </nav>
    </>
  )
}

function SheetTile({
  item,
  pinned,
  onNavigate,
  onToggle,
}: {
  item: NavItem
  pinned: boolean
  onNavigate: () => void
  onToggle: () => void
}) {
  return (
    <div className="relative">
      <NavLink
        to={item.to}
        end={item.to === '/'}
        onClick={onNavigate}
        className={({ isActive }) =>
          clsx(
            'flex flex-col items-center justify-center gap-1.5 h-20 rounded-xl text-[11px] text-center px-1 transition-colors',
            isActive
              ? 'text-accent bg-accent/[0.10] ring-1 ring-accent/25'
              : 'text-text-secondary bg-tint/[0.025] ring-1 ring-border hover:bg-tint/[0.05]'
          )
        }
      >
        <Icon name={item.icon} size={20} />
        <span className="font-medium leading-tight">{item.label}</span>
      </NavLink>
      <button
        type="button"
        onClick={onToggle}
        title={pinned ? 'Unpin' : 'Pin to bottom bar'}
        className={clsx(
          'absolute top-1 right-1 grid place-items-center w-6 h-6 rounded-md transition-colors',
          pinned ? 'text-accent' : 'text-text-muted/60 hover:text-text-secondary'
        )}
      >
        <Icon name="star" size={13} filled={pinned} />
      </button>
    </div>
  )
}
