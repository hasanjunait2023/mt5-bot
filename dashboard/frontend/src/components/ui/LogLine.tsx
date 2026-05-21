import clsx from 'clsx'
import type { LogEntry } from '../../types/trading'

interface Props {
  entry: LogEntry
}

const LEVEL_COLOR: Record<string, string> = {
  INFO:    'text-text-primary',
  WARNING: 'text-warning',
  ERROR:   'text-loss',
  DEBUG:   'text-text-muted',
}

const LEVEL_TAG: Record<string, string> = {
  INFO:    'text-text-secondary',
  WARNING: 'text-warning',
  ERROR:   'text-loss',
  DEBUG:   'text-text-muted',
}

function getRowClass(entry: LogEntry): string {
  const raw = entry.raw ?? entry.message
  if (entry.level === 'ERROR')                       return 'border-loss/70 bg-loss/[0.04]'
  if (raw.includes('>>') || raw.includes('BUY'))     return 'border-profit/70'
  if (raw.includes('SELL') || raw.includes('FAIL'))  return 'border-loss/70'
  if (entry.level === 'WARNING')                     return 'border-warning/70'
  return 'border-transparent'
}

export function LogLine({ entry }: Props) {
  return (
    <div
      className={clsx(
        'flex items-start gap-3 py-1 pl-2.5 font-mono text-xs border-l-2 rounded-r transition-colors hover:bg-white/[0.025]',
        getRowClass(entry),
      )}
    >
      <span className="text-text-muted shrink-0 w-32 tabular-nums">{entry.timestamp}</span>
      <span className={clsx('w-14 shrink-0 font-semibold tracking-wide', LEVEL_TAG[entry.level])}>
        {entry.level}
      </span>
      <span className={clsx('flex-1 break-all', LEVEL_COLOR[entry.level])}>{entry.message}</span>
    </div>
  )
}
