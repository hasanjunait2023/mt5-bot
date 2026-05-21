import clsx from 'clsx'

interface Props {
  children: React.ReactNode
  variant?: 'buy' | 'sell' | 'neutral' | 'info'
}

const STYLES = {
  buy:     'text-profit ring-1 ring-profit/30 bg-profit/10',
  sell:    'text-loss ring-1 ring-loss/30 bg-loss/10',
  neutral: 'text-text-secondary ring-1 ring-border bg-white/[0.04]',
  info:    'text-accent ring-1 ring-accent/30 bg-accent/10',
}

export function Badge({ children, variant = 'neutral' }: Props) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold font-mono tracking-wide',
        STYLES[variant],
      )}
    >
      {children}
    </span>
  )
}
