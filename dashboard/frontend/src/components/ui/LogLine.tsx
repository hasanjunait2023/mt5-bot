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

function getRowClass(entry: LogEntry): string {
  const raw = entry.raw ?? entry.message
  if (entry.level === 'ERROR')                 return 'border-l-2 border-loss pl-2'
  if (raw.includes('>>') || raw.includes('BUY'))   return 'border-l-2 border-profit pl-2'
  if (raw.includes('SELL') || raw.includes('FAIL')) return 'border-l-2 border-loss pl-2'
  if (entry.level === 'WARNING')               return 'border-l-2 border-warning pl-2'
  return 'border-l-2 border-transparent pl-2'
}

export function LogLine({ entry }: Props) {
  return (
    <div className={clsx('flex items-start gap-3 py-0.5 font-mono text-xs', getRowClass(entry))}>
      <span className="text-text-muted shrink-0 w-36">{entry.timestamp}</span>
      <span className={clsx('w-16 shrink-0 font-semibold', LEVEL_COLOR[entry.level])}>{entry.level}</span>
      <span className={clsx('flex-1 break-all', LEVEL_COLOR[entry.level])}>{entry.message}</span>
    </div>
  )
}
