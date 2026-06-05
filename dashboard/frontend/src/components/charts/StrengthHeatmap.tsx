// 8-major × 3-session strength matrix. Cell color tracks the -7..+7 score.

const SESSION_COLS: { key: string; label: string }[] = [
  { key: 'asian', label: 'Asian' },
  { key: 'london_1h', label: 'London' },
  { key: 'newyork', label: 'New York' },
]

function cellColor(v: number): string {
  if (v >= 5) return 'bg-emerald-400/80 text-bg-base'
  if (v >= 2) return 'bg-emerald-400/35 text-emerald-200'
  if (v > -2) return 'bg-bg-elevated text-text-muted'
  if (v > -5) return 'bg-rose-400/35 text-rose-200'
  return 'bg-rose-400/80 text-bg-base'
}

interface Props {
  majors: string[]
  // sessions[sessionKey].score[currency] = -7..+7
  sessions: Record<string, { score: Record<string, number> }>
}

export function StrengthHeatmap({ majors, sessions }: Props) {
  if (!majors.length) {
    return <div className="h-20 grid place-items-center text-text-muted text-sm">No strength data yet</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="text-xs font-mono border-collapse w-full">
        <thead>
          <tr>
            <th className="text-text-muted pr-2 text-left font-normal" />
            {SESSION_COLS.map(c => (
              <th key={c.key} className="text-text-muted px-1 font-normal text-center">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {majors.map(ccy => (
            <tr key={ccy}>
              <td className="text-text-secondary pr-2 py-0.5 font-semibold">{ccy}</td>
              {SESSION_COLS.map(c => {
                const v = sessions?.[c.key]?.score?.[ccy]
                return (
                  <td key={c.key} className="px-0.5 py-0.5">
                    {v !== undefined ? (
                      <div className={`text-center rounded py-1 ${cellColor(v)}`}>
                        {v > 0 ? '+' : ''}{v}
                      </div>
                    ) : (
                      <div className="h-6 rounded bg-bg-surface" />
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
