interface Props {
  name: IconName
  size?: number
  className?: string
}

export type IconName =
  | 'overview' | 'positions' | 'history' | 'bots'
  | 'reports' | 'logs' | 'eas' | 'settings' | 'system' | 'telegram'

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
  bots: (
    <>
      <rect x="4" y="8" width="16" height="11" rx="2.5" />
      <path d="M12 8V4M9 4h6" />
      <circle cx="9.5" cy="13" r="1.2" />
      <circle cx="14.5" cy="13" r="1.2" />
    </>
  ),
  reports: (
    <>
      <path d="M3 17l5-5 4 3 8-8" />
      <path d="M21 7v5h-5" />
    </>
  ),
  logs: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 2.5L7 14M13 14h4" />
    </>
  ),
  eas: (
    <>
      <rect x="5" y="6" width="14" height="14" rx="2.5" />
      <path d="M9 6V3h6v3M2 12h3M19 12h3M9 11v3M15 11v3" />
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
}

export function Icon({ name, size = 18, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
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
