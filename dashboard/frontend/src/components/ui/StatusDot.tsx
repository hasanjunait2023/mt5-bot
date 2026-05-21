import clsx from 'clsx'

type Status = 'running' | 'stopped' | 'warning' | 'offline'

interface Props {
  status: Status
  label?: string
}

const DOT: Record<Status, string> = {
  running: 'bg-profit',
  stopped: 'bg-loss',
  warning: 'bg-warning',
  offline: 'bg-text-muted',
}

export function StatusDot({ status, label }: Props) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative flex w-2 h-2 shrink-0">
        {status === 'running' && (
          <span className="absolute inline-flex w-full h-full rounded-full bg-profit opacity-60 animate-glow-ring" />
        )}
        {status === 'warning' && (
          <span className="absolute inline-flex w-full h-full rounded-full bg-warning animate-pulse2" />
        )}
        <span className={clsx('relative w-2 h-2 rounded-full', DOT[status])} />
      </span>
      {label && <span className="text-text-secondary text-sm">{label}</span>}
    </div>
  )
}
