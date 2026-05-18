const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

interface Props {
  data: Record<string, number>
}

function color(v: number): string {
  if (v > 5)  return 'bg-profit text-bg-base'
  if (v > 0)  return 'bg-profit/40 text-profit'
  if (v === 0) return 'bg-bg-elevated text-text-muted'
  if (v > -5) return 'bg-loss/40 text-loss'
  return 'bg-loss text-bg-base'
}

export function MonthlyHeatmap({ data }: Props) {
  const entries = Object.entries(data)
  if (!entries.length) {
    return (
      <div className="h-20 flex items-center justify-center text-text-muted text-sm">No monthly data yet</div>
    )
  }

  const years = [...new Set(entries.map(([k]) => k.slice(0, 4)))].sort()

  return (
    <div className="overflow-x-auto">
      <table className="text-xs font-mono border-collapse">
        <thead>
          <tr>
            <th className="text-text-muted pr-2 text-right" />
            {MONTHS.map(m => <th key={m} className="text-text-muted px-1 font-normal">{m}</th>)}
          </tr>
        </thead>
        <tbody>
          {years.map(year => (
            <tr key={year}>
              <td className="text-text-secondary pr-2 text-right py-0.5">{year}</td>
              {MONTHS.map((_, i) => {
                const key = `${year}-${String(i + 1).padStart(2, '0')}`
                const val = data[key]
                return (
                  <td key={i} className="px-0.5 py-0.5">
                    {val !== undefined ? (
                      <div className={`w-12 text-center rounded py-0.5 ${color(val)}`}>
                        {val > 0 ? '+' : ''}{val.toFixed(1)}%
                      </div>
                    ) : (
                      <div className="w-12 h-5 rounded bg-bg-surface" />
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
