import type { IconName } from '../ui/Icon'

export type NavItem = { to: string; label: string; icon: IconName }
export type NavGroup = { label: string; items: NavItem[] }

// Single source of truth for navigation, organised into labelled sections so
// the sidebar reads as grouped clusters instead of one long undifferentiated
// list. Both the desktop Sidebar and the mobile bottom-nav render from this —
// so a page can never be reachable on one and invisible on the other.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Trading',
    items: [
      { to: '/',          label: 'Overview',          icon: 'overview' },
      { to: '/positions', label: 'Positions',         icon: 'positions' },
      { to: '/history',   label: 'History',           icon: 'history' },
      { to: '/pending',   label: 'Pending & Stalled', icon: 'pending' },
      { to: '/journal',   label: 'Trade Journal',     icon: 'journal' },
    ],
  },
  {
    label: 'Agents & Desks',
    items: [
      { to: '/fleet',   label: 'Agent Fleet',   icon: 'fleet' },
      { to: '/bots',    label: 'Bots & Agents', icon: 'bots' },
      { to: '/system',  label: 'System Agents', icon: 'system' },
      { to: '/iconic',  label: 'Iconic Trader', icon: 'iconic' },
      { to: '/jtcc',    label: 'JTCC Signals',  icon: 'jtcc' },
      { to: '/asia',    label: 'Asia Desk',     icon: 'asia' },
      { to: '/scalp',    label: 'Gold Scalp',       icon: 'gold' },
      { to: '/strength', label: 'Currency Strength', icon: 'signals' },
      { to: '/signals',  label: 'Signals',          icon: 'signals' },
      { to: '/desk',     label: 'Alpha Desk',       icon: 'desk' },
    ],
  },
  {
    label: 'Analytics',
    items: [
      { to: '/lab',      label: 'Strategy Lab',    icon: 'strategy' },
      { to: '/strategy', label: 'Strategy Perf',   icon: 'strategy' },
      { to: '/reports',  label: 'Reports',         icon: 'reports' },
      { to: '/cpp',      label: 'CPP Portfolio',   icon: 'cpp' },
      { to: '/vp',       label: 'Volume Profile',  icon: 'vp' },
      { to: '/eas',      label: 'Expert Advisors', icon: 'eas' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/logs',     label: 'Logs',        icon: 'logs' },
      { to: '/telegram', label: 'Telegram HQ', icon: 'telegram' },
      { to: '/settings', label: 'Settings',    icon: 'settings' },
    ],
  },
]

// Flat list — used for path → item lookups (favourites, mobile tabs).
export const NAV: NavItem[] = NAV_GROUPS.flatMap(g => g.items)

export const navByPath = (to: string): NavItem | undefined => NAV.find(n => n.to === to)

// Default mobile bottom tabs when the user hasn't pinned any favourites yet.
export const MOBILE_PRIMARY = ['/', '/positions', '/eas', '/journal', '/bots']
