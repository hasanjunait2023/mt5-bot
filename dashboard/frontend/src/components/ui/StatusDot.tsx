import clsx from 'clsx'

type Status = 'running' | 'stopped' | 'warning' | 'offline'

interface Props {
  status: Status
  label?: string
}

const COLOR: Record<Status, string> = {
  running: 'bg-profit animate-pulse2',
  stopped: 'bg-loss',
  warning: 'bg-warning',
  offline: 'bg-text-muted',
}

export function StatusDot({ status, label }: Props) {
  return (
    <div className="flex items-center gap-2">
      <div className={clsx('w-2 h-2 rounded-full shrink-0', COLOR[status])} />
      {label && <span className="text-text-secondary text-sm">{label}</span>}
    </div>
  )
}
