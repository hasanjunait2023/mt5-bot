import type { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  right?: ReactNode
}

/** Consistent page heading — the Z-pattern entry point on every route. */
export function PageHeader({ title, subtitle, right }: Props) {
  return (
    <header className="flex items-end justify-between gap-4">
      <div>
        <h1 className="text-text-primary text-xl md:text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-text-secondary text-sm mt-0.5">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </header>
  )
}
