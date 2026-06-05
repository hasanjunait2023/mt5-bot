interface Props {
  name: IconName
  size?: number
  className?: string
  /** Fill the glyph with currentColor (used for the active favourite star). */
  filled?: boolean
}

export type IconName =
  | 'overview' | 'positions' | 'history' | 'pending' | 'journal'
  | 'fleet' | 'bots' | 'system' | 'iconic' | 'jtcc' | 'asia' | 'gold'
  | 'signals' | 'desk' | 'strategy' | 'reports' | 'cpp' | 'vp' | 'eas'
  | 'logs' | 'telegram' | 'settings' | 'hub' | 'star' | 'grip' | 'pin'
  | 'terminal'

const PATHS: Record<IconName, JSX.Element> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </>
  ),
  positions: (
    <>
      <path d="M3 3v18h18" />
      <path d="M7 14l3.5-4 3 2.5L20 6" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4l3 2" />
    </>
  ),
  pending: (
    <>
      <path d="M6 3h12M6 21h12" />
      <path d="M7 3c0 4 4 5.5 5 9 1-3.5 5-5 5-9" />
      <path d="M7 21c0-4 4-5.5 5-9 1 3.5 5 5 5 9" />
    </>
  ),
  journal: (
    <>
      <path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v18H6.5A1.5 1.5 0 0 1 5 19.5z" />
      <path d="M9 3v18M12 8h4M12 12h4" />
    </>
  ),
  fleet: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
    </>
  ),
  bots: (
    <>
      <rect x="4" y="8" width="16" height="11" rx="2.5" />
      <path d="M12 8V4M9 4h6" />
      <circle cx="9.5" cy="13" r="1.2" />
      <circle cx="14.5" cy="13" r="1.2" />
    </>
  ),
  system: (
    <>
      <circle cx="12" cy="12" r="2.2" />
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M7 6h4M13 6h4M7 18h4M13 18h4M5 8v3M19 8v3M5 13v3M19 13v3M10.5 11l-3-3M13.5 11l3-3M10.5 13l-3 3M13.5 13l3 3" />
    </>
  ),
  iconic: (
    <path d="M12 2.5l2.9 5.9 6.5.9-4.7 4.6 1.1 6.4L12 17.8 6.2 20.7l1.1-6.4L2.6 9.7l6.5-.9z" />
  ),
  jtcc: (
    <path d="M2 12h4l2.5-7 4 16 2.5-9h7" />
  ),
  asia: (
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  ),
  gold: (
    <>
      <ellipse cx="12" cy="6.5" rx="7" ry="2.5" />
      <path d="M5 6.5v5c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-5" />
      <path d="M5 11.5v5c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-5" />
    </>
  ),
  signals: (
    <>
      <circle cx="12" cy="12" r="2" />
      <path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 15.5a5 5 0 0 0 0-7" />
      <path d="M6 6a9 9 0 0 0 0 12M18 18a9 9 0 0 0 0-12" />
    </>
  ),
  desk: (
    <>
      <path d="M6 3v4M6 16v5M5 7h2v9H5z" />
      <path d="M13 3v6M13 15v6M12 9h2v6h-2z" />
      <path d="M19 3v3M19 13v8M18 6h2v7h-2z" />
    </>
  ),
  strategy: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.8" fill="currentColor" stroke="none" />
    </>
  ),
  reports: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2.5" />
      <path d="M8 16v-4M12 16V8M16 16v-6" />
    </>
  ),
  cpp: (
    <>
      <path d="M21 12a9 9 0 1 1-9-9v9z" />
      <path d="M13 3.5a8.5 8.5 0 0 1 7.5 7.5H13z" />
    </>
  ),
  vp: (
    <path d="M3 21V11M8 21V6M13 21v-8M18 21V4" />
  ),
  eas: (
    <>
      <rect x="5" y="6" width="14" height="14" rx="2.5" />
      <path d="M9 6V3h6v3M2 12h3M19 12h3M9 11v3M15 11v3" />
    </>
  ),
  logs: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 2.5L7 14M13 14h4" />
    </>
  ),
  telegram: (
    <>
      <path d="M21.5 4L2.5 11.5l6 2 2.5 6.5 3-4 5 3.5z" />
      <path d="M8.5 13.5L18 6.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 13.5a7.8 7.8 0 0 0 0-3l1.7-1.3-1.8-3.1-2 .8a7.7 7.7 0 0 0-2.6-1.5l-.3-2.1h-3.6l-.3 2.1A7.7 7.7 0 0 0 7.3 6L5.3 5.2 3.5 8.3l1.7 1.3a7.8 7.8 0 0 0 0 3L3.5 14l1.8 3.1 2-.8a7.7 7.7 0 0 0 2.6 1.5l.3 2.1h3.6l.3-2.1a7.7 7.7 0 0 0 2.6-1.5l2 .8 1.8-3.1z" />
    </>
  ),
  hub: (
    <>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="8" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
      <rect x="13" y="13" width="8" height="8" rx="1.5" />
    </>
  ),
  star: (
    <path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.2l5.9-.9z" />
  ),
  grip: (
    <>
      <circle cx="9" cy="6" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="15" cy="6" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="9" cy="18" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="15" cy="18" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  pin: (
    <>
      <path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z" />
      <path d="M12 14v7" />
    </>
  ),
  terminal: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 3-3 3" />
      <path d="M13 15h4" />
    </>
  ),
}

export function Icon({ name, size = 18, className, filled = false }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}
