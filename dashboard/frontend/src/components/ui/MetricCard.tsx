import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useCountUp, useValueFlash } from '../../hooks/useCountUp'

type Tone = 'neutral' | 'profit' | 'loss' | 'accent'

interface Props {
  label: string
  value: string | number
  delta?: number
  deltaLabel?: string
  prefix?: string
  suffix?: string
  positive?: boolean
  right?: ReactNode
  /** Larger figure + accent edge — use for the single most important metric */
  hero?: boolean
  tone?: Tone
}

const TONE_RING: Record<Tone, string> = {
  neutral: 'ring-border',
  profit: 'ring-profit/25',
  loss: 'ring-loss/25',
  accent: 'ring-accent/30',
}
const TONE_GLOW: Record<Tone, string> = {
  neutral: '',
  profit: 'shadow-glow-profit',
  loss: 'shadow-glow-loss',
  accent: 'shadow-glow-accent',
}

export function MetricCard({
  label, value, delta, deltaLabel, prefix = '', suffix = '',
  positive, right, hero = false, tone = 'neutral',
}: Props) {
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
        TONE_RING[tone],
        tone !== 'neutral' && TONE_GLOW[tone],
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
            tone === 'profit' && 'text-profit',
            tone === 'loss' && 'text-loss',
            tone === 'accent' && 'text-text-primary',
            tone === 'neutral' && 'text-text-primary',
            flash === 'up' && 'animate-flash-up',
            flash === 'down' && 'animate-flash-down',
          )}
        >
          {prefix}{shown}{suffix}
        </span>
      </div>

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
