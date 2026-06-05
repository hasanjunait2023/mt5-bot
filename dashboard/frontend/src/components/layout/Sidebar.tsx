import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { Icon } from '../ui/Icon'
import { NAV_GROUPS, navByPath, type NavItem } from './navItems'
import { useFavorites } from '../../hooks/useFavorites'

export function Sidebar() {
  const { favorites, isFavorite, toggle, move } = useFavorites()
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  const favItems = favorites.map(navByPath).filter((n): n is NavItem => Boolean(n))

  return (
    <aside className="hidden md:flex flex-col w-[238px] shrink-0
                      bg-bg-surface/55 backdrop-blur-xl border-r border-border">
      <nav className="flex-1 min-h-0 overflow-y-auto px-3 pt-3 pb-2">
        {/* ── Favourites — user-pinned, drag to reorder ─────────────── */}
        {favItems.length > 0 && (
          <div className="mb-3">
            <SectionLabel>
              <Icon name="star" size={11} filled className="text-accent" />
              Favourites
            </SectionLabel>
            <ul className="mt-1.5 space-y-0.5">
              {favItems.map((item, idx) => (
                <li
                  key={item.to}
                  draggable
                  onDragStart={() => setDragFrom(idx)}
                  onDragEnter={() => setDragOver(idx)}
                  onDragOver={e => e.preventDefault()}
                  onDrop={() => {
                    if (dragFrom !== null) move(dragFrom, idx)
                    setDragFrom(null)
                    setDragOver(null)
                  }}
                  onDragEnd={() => {
                    setDragFrom(null)
                    setDragOver(null)
                  }}
                  className={clsx(
                    'rounded-lg transition-opacity',
                    dragFrom === idx && 'opacity-40',
                    dragOver === idx && dragFrom !== idx && 'ring-1 ring-accent/40'
                  )}
                >
                  <NavRow item={item} pinned draggable onToggle={() => toggle(item.to)} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ── Grouped sections ──────────────────────────────────────── */}
        {NAV_GROUPS.map(group => (
          <div key={group.label} className="mb-3 last:mb-0">
            <SectionLabel>{group.label}</SectionLabel>
            <ul className="mt-1.5 space-y-0.5">
              {group.items.map(item => (
                <li key={item.to}>
                  <NavRow
                    item={item}
                    pinned={isFavorite(item.to)}
                    onToggle={() => toggle(item.to)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="m-3 p-3 rounded-xl bg-tint/[0.025] ring-1 ring-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse2" />
          <p className="text-text-secondary text-[11px] font-medium">Monitor active</p>
        </div>
        <p className="text-text-muted text-[11px] mt-1">MT5 Bot · v1.0</p>
      </div>
    </aside>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 px-3 pt-1 text-[10px] font-semibold uppercase
                    tracking-[0.16em] text-text-muted/80 select-none">
      {children}
    </div>
  )
}

function NavRow({
  item,
  pinned,
  draggable = false,
  onToggle,
}: {
  item: NavItem
  pinned: boolean
  draggable?: boolean
  onToggle: () => void
}) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        clsx(
          'group relative flex items-center gap-2.5 pl-3 pr-2 h-9 rounded-lg text-[13px]',
          'transition-all duration-200',
          isActive
            ? 'text-text-primary bg-gradient-to-r from-accent/[0.14] to-transparent ring-1 ring-accent/20'
            : 'text-text-secondary hover:text-text-primary hover:bg-tint/[0.04]'
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* active accent bar */}
          <span
            className={clsx(
              'absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full transition-all duration-200',
              isActive ? 'h-5 bg-accent shadow-glow-accent' : 'h-0 bg-transparent'
            )}
          />
          {draggable && (
            <span
              className="absolute -left-0.5 opacity-0 group-hover:opacity-100 cursor-grab active:cursor-grabbing
                         text-text-muted/60 transition-opacity"
              onClick={e => e.preventDefault()}
              title="Drag to reorder"
            >
              <Icon name="grip" size={12} />
            </span>
          )}
          <Icon
            name={item.icon}
            size={17}
            className={clsx(
              'shrink-0 transition-colors',
              isActive ? 'text-accent' : 'text-text-muted group-hover:text-text-secondary'
            )}
          />
          <span className="font-medium tracking-tight truncate flex-1">{item.label}</span>

          {/* pin / unpin star — reveals on hover, stays visible when pinned */}
          <button
            type="button"
            onClick={e => {
              e.preventDefault()
              e.stopPropagation()
              onToggle()
            }}
            title={pinned ? 'Unpin from favourites' : 'Pin to favourites'}
            className={clsx(
              'shrink-0 grid place-items-center w-6 h-6 rounded-md transition-all',
              pinned
                ? 'text-accent opacity-100 hover:bg-tint/[0.06]'
                : 'text-text-muted/70 opacity-0 group-hover:opacity-100 hover:text-text-secondary hover:bg-tint/[0.06]'
            )}
          >
            <Icon name="star" size={13} filled={pinned} />
          </button>
        </>
      )}
    </NavLink>
  )
}
