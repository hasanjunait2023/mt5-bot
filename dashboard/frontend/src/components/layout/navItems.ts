import type { IconName } from '../ui/Icon'

export type NavItem = { to: string; label: string; icon: IconName }

// Single source of truth for navigation. Both the desktop Sidebar and the
// mobile bottom-nav render from this — so a page can never be reachable on one
// and invisible on the other (which is how /journal went missing on mobile).
export const NAV: NavItem[] = [
  { to: '/',          label: 'Overview',        icon: 'overview' },
  { to: '/fleet',     label: 'Agent Fleet',     icon: 'bots' },
  { to: '/strategy',  label: 'Strategy Perf',   icon: 'reports' },
  { to: '/positions', label: 'Positions',       icon: 'positions' },
  { to: '/history',   label: 'History',         icon: 'history' },
  { to: '/bots',      label: 'Bots & Agents',   icon: 'bots' },
  { to: '/system',    label: 'System Agents',   icon: 'system' },
  { to: '/pending',   label: 'Pending & Stalled', icon: 'logs' },
  { to: '/reports',   label: 'Reports',         icon: 'reports' },
  { to: '/logs',      label: 'Logs',            icon: 'logs' },
  { to: '/eas',       label: 'Expert Advisors', icon: 'eas' },
  { to: '/cpp',       label: 'CPP Portfolio',   icon: 'reports' },
  { to: '/jtcc',      label: 'JTCC Signals',     icon: 'bots' },
  { to: '/signals',   label: 'Signals',          icon: 'system' },
  { to: '/desk',      label: 'Alpha Desk',       icon: 'reports' },
  { to: '/iconic',    label: 'Iconic Trader',    icon: 'bots' },
  { to: '/asia',      label: 'Asia Desk',        icon: 'bots' },
  { to: '/scalp',     label: 'Gold Scalp',       icon: 'bots' },
  { to: '/vp',        label: 'Volume Profile',   icon: 'reports' },
  { to: '/journal',   label: 'Trade Journal',    icon: 'history' },
  { to: '/telegram',  label: 'Telegram HQ',     icon: 'telegram' },
  { to: '/settings',  label: 'Settings',        icon: 'settings' },
]

// The handful pinned as fixed tabs on the mobile bottom bar; everything else
// is reached via the "More" tab.
export const MOBILE_PRIMARY = ['/', '/positions', '/eas', '/journal', '/bots']
