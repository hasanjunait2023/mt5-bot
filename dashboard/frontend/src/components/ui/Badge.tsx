import clsx from 'clsx'

interface Props {
  children: React.ReactNode
  variant?: 'buy' | 'sell' | 'neutral' | 'info'
}

const STYLES = {
  buy:     'text-profit border border-profit/30 bg-bg-overlay',
  sell:    'text-loss border border-loss/30 bg-bg-overlay',
  neutral: 'text-text-secondary border border-border bg-bg-overlay',
  info:    'text-accent border border-accent/30 bg-bg-overlay',
}

export function Badge({ children, variant = 'neutral' }: Props) {
  return (
    <span className={clsx('inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold font-mono', STYLES[variant])}>
      {children}
    </span>
  )
}
