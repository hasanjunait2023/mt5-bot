import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useCountUp, useValueFlash } from '../../hooks/useCountUp'

type CanonTone = 'neutral' | 'profit' | 'loss' | 'accent' | 'warning'
// Color-word aliases (green/red/yellow/gray) map onto the semantic tones so
// callers can use whichever vocabulary reads best at the call site.
type Tone = CanonTone | 'green' | 'red' | 'yellow' | 'gray'

interface Props {
  label: string
  value: string | number
  delta?: number
  deltaLabel?: string
  prefix?: string
  suffix?: string
  positive?: boolean
  right?: ReactNode
  /** Muted subtitle under the figure (e.g. "3 pending", "profit factor"). */
  sub?: ReactNode
  /** Larger figure + accent edge — use for the single most important metric */
  hero?: boolean
  tone?: Tone
}

const CANON: Record<Tone, CanonTone> = {
  neutral: 'neutral', profit: 'profit', loss: 'loss', accent: 'accent', warning: 'warning',
  green: 'profit', red: 'loss', yellow: 'warning', gray: 'neutral',
}
const TONE_RING: Record<CanonTone, string> = {
  neutral: 'ring-border',
  profit: 'ring-profit/25',
  loss: 'ring-loss/25',
  accent: 'ring-accent/30',
  warning: 'ring-warning/30',
}
const TONE_GLOW: Record<CanonTone, string> = {
  neutral: '',
  profit: 'shadow-glow-profit',
  loss: 'shadow-glow-loss',
  accent: 'shadow-glow-accent',
  warning: '',
}

export function MetricCard({
  label, value, delta, deltaLabel, prefix = '', suffix = '',
  positive, right, sub, hero = false, tone = 'neutral',
}: Props) {
  const tn = CANON[tone]
  const isNum = typeof value === 'number'
  const animated = useCountUp(isNum ? (value as number) : 0)
  const flash = useValueFlash(isNum ? (value as number) : 0)

  const shown = isNum
    ? animated.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value

  const isPos =
    positive !== undefined ? positive : typeof delta === 'number' ? delta >= 0 : undefined
  const deltaColor =
    isPos === undefined ? 'text-text-secondary' : isPos ? 'text-profit' : 'text-loss'

  return (
    <div
      className={clsx(
        'glass glass-hover relative overflow-hidden p-5 flex flex-col gap-2.5 min-w-0 ring-1',
        TONE_RING[tn],
        tn !== 'neutral' && TONE_GLOW[tn],
      )}
    >
      {/* top sheen */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />

      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow truncate">{label}</p>
        {right && <div className="shrink-0 opacity-90">{right}</div>}
      </div>

      <div className="flex items-end gap-2">
        <span
          className={clsx(
            'font-mono font-bold leading-none tracking-tight font-tabular rounded px-1 -mx-1',
            hero ? 'text-3xl md:text-[2.1rem]' : 'text-2xl',
            tn === 'profit' && 'text-profit',
            tn === 'loss' && 'text-loss',
            tn === 'warning' && 'text-warning',
            tn === 'accent' && 'text-text-primary',
            tn === 'neutral' && 'text-text-primary',
            flash === 'up' && 'animate-flash-up',
            flash === 'down' && 'animate-flash-down',
          )}
        >
          {prefix}{shown}{suffix}
        </span>
      </div>

      {sub && <p className="text-xs text-text-muted truncate">{sub}</p>}

      {delta !== undefined && (
        <p className={clsx('text-xs font-mono flex items-center gap-1', deltaColor)}>
          <span>{delta >= 0 ? '▲' : '▼'}</span>
          <span className="font-tabular">{Math.abs(delta).toFixed(2)}{suffix}</span>
          {deltaLabel && <span className="text-text-muted ml-0.5">{deltaLabel}</span>}
        </p>
      )}
    </div>
  )
}
