import clsx from 'clsx'
import type { ReactNode } from 'react'

interface Props {
  label: string
  value: string | number
  delta?: number
  deltaLabel?: string
  prefix?: string
  suffix?: string
  positive?: boolean
  right?: ReactNode
}

export function MetricCard({ label, value, delta, deltaLabel, prefix = '', suffix = '', positive, right }: Props) {
  const isPos = positive !== undefined ? positive : (typeof delta === 'number' ? delta >= 0 : undefined)
  const deltaColor = isPos === undefined ? 'text-text-secondary' : isPos ? 'text-profit' : 'text-loss'

  return (
    <div className="bg-bg-surface border border-border rounded-lg p-5 flex flex-col gap-1 min-w-0">
      <p className="text-text-secondary text-xs uppercase tracking-widest font-sans">{label}</p>
      <div className="flex items-end justify-between gap-2">
        <span className="text-text-primary font-mono text-2xl font-bold leading-none truncate">
          {prefix}{typeof value === 'number' ? value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value}{suffix}
        </span>
        {right && <div className="shrink-0">{right}</div>}
      </div>
      {delta !== undefined && (
        <p className={clsx('text-xs font-mono', deltaColor)}>
          {delta >= 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(2)}{suffix}
          {deltaLabel && <span className="text-text-muted ml-1">{deltaLabel}</span>}
        </p>
      )}
    </div>
  )
}
