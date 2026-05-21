import clsx from 'clsx'
import type { ReactNode } from 'react'

interface Props {
  title?: string
  right?: ReactNode
  children: ReactNode
  className?: string
  /** cascade index for the staggered entrance reveal */
  i?: number
  bare?: boolean
}

export function Panel({ title, right, children, className, i, bare = false }: Props) {
  return (
    <section
      className={clsx('glass reveal', bare ? 'p-0' : 'p-5', className)}
      style={i !== undefined ? ({ '--i': i } as React.CSSProperties) : undefined}
    >
      {title && (
        <div className="flex items-center justify-between gap-3 mb-4">
          <h2 className="eyebrow">{title}</h2>
          {right && <div className="shrink-0">{right}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
