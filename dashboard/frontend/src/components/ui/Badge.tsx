import clsx from 'clsx'

type Variant = 'buy' | 'sell' | 'neutral' | 'info'
type Tone = 'green' | 'red' | 'yellow' | 'orange' | 'gray' | 'blue'

interface Props {
  children: React.ReactNode
  variant?: Variant
  /** Color-word tone. When set, overrides `variant`. */
  tone?: Tone
}

const STYLES: Record<Variant, string> = {
  buy:     'text-profit ring-1 ring-profit/30 bg-profit/10',
  sell:    'text-loss ring-1 ring-loss/30 bg-loss/10',
  neutral: 'text-text-secondary ring-1 ring-border bg-tint/[0.04]',
  info:    'text-accent ring-1 ring-accent/30 bg-accent/10',
}

const TONE_STYLES: Record<Tone, string> = {
  green:  'text-profit ring-1 ring-profit/30 bg-profit/10',
  red:    'text-loss ring-1 ring-loss/30 bg-loss/10',
  yellow: 'text-warning ring-1 ring-warning/30 bg-warning/10',
  orange: 'text-orange-400 ring-1 ring-orange-400/30 bg-orange-400/10',
  gray:   'text-text-secondary ring-1 ring-border bg-tint/[0.04]',
  blue:   'text-accent ring-1 ring-accent/30 bg-accent/10',
}

export function Badge({ children, variant = 'neutral', tone }: Props) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold font-mono tracking-wide',
        tone ? TONE_STYLES[tone] : STYLES[variant],
      )}
    >
      {children}
    </span>
  )
}
