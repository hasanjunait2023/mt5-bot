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
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm border-collapse min-w-max">
        <thead>
          <tr className="bg-bg-elevated">
            {columns.map(col => (
              <th
                key={col.key}
                className={`px-3 py-2 text-text-secondary font-sans text-xs uppercase tracking-widest font-medium whitespace-nowrap text-${col.align ?? 'left'}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-3 py-8 text-center text-text-muted">
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map(row => (
              <tr key={keyFn(row)} className="border-t border-border hover:bg-bg-elevated transition-colors">
                {columns.map(col => (
                  <td
                    key={col.key}
                    className={`px-3 py-2.5 font-mono text-text-primary whitespace-nowrap text-${col.align ?? 'left'}`}
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
