import type { ReactNode } from 'react'

interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  align?: 'left' | 'right' | 'center'
}

interface Props<T> {
  columns: Column<T>[]
  data: T[]
  keyFn: (row: T) => string | number
  emptyText?: string
}

export function Table<T>({ columns, data, keyFn, emptyText = 'No data' }: Props<T>) {
  return (
    <div className="glass overflow-x-auto">
      <table className="w-full text-sm border-collapse min-w-max">
        <thead>
          <tr className="sticky top-0 z-10 bg-bg-elevated/90 backdrop-blur-sm">
            {columns.map(col => (
              <th
                key={col.key}
                className={`px-3.5 py-2.5 text-text-secondary font-sans text-[11px] uppercase tracking-[0.12em] font-semibold whitespace-nowrap text-${col.align ?? 'left'} border-b border-border`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-12 text-center text-text-muted">
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map(row => (
              <tr
                key={keyFn(row)}
                className="border-b border-white/[0.05] last:border-0 hover:bg-white/[0.035] transition-colors"
              >
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={`px-3.5 py-2.5 font-mono font-tabular text-text-primary whitespace-nowrap text-${col.align ?? 'left'}`}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
