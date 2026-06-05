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
      <div className="flex items-stretch gap-3">
        <span
          aria-hidden
          className="w-[3px] shrink-0 self-stretch rounded-full bg-gradient-to-b from-accent to-accent-dim shadow-[0_0_12px_-2px_rgba(59,130,246,0.6)]"
        />
        <div>
          <h1 className="text-text-primary text-xl md:text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="text-text-secondary text-sm mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </header>
  )
}
