// Centered ±7 strength bars for the 8 majors. Score is the net-pair-win count
// (-7..+7) from the strength engine. Tier color: STRONG/WEAK saturated, mid
// muted, neutral grey.

export interface StrengthRow {
  currency: string
  score: number   // integer in [-7, +7]
}

function barColor(score: number): string {
  const a = Math.abs(score)
  if (score >= 0) return a >= 5 ? 'bg-emerald-400/80' : a >= 2 ? 'bg-emerald-400/45' : 'bg-tint/15'
  return a >= 5 ? 'bg-rose-400/80' : a >= 2 ? 'bg-rose-400/45' : 'bg-tint/15'
}

function textColor(score: number): string {
  if (score === 0) return 'text-text-muted'
  return score > 0 ? 'text-emerald-300' : 'text-rose-300'
}

export function StrengthMeter({ rows }: { rows: StrengthRow[] }) {
  if (!rows.length) {
    return <div className="h-24 grid place-items-center text-text-muted text-xs">No data</div>
  }
  // Stable currency order, strongest first for quick reading.
  const sorted = [...rows].sort((a, b) => b.score - a.score)
  return (
    <div className="space-y-1.5">
      {sorted.map(r => {
        const pct = Math.min(100, (Math.abs(r.score) / 7) * 50)   // half-width max
        const strong = r.score >= 0
        return (
          <div key={r.currency} className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold w-9 shrink-0">{r.currency}</span>
            <div className="relative flex-1 h-3 rounded bg-tint/[0.04] ring-1 ring-border">
              <div className="absolute top-0 bottom-0 left-1/2 w-px bg-tint/20" />
              <div
                className={`absolute top-0 bottom-0 rounded-sm ${barColor(r.score)}`}
                style={strong ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
              />
            </div>
            <span className={`font-mono text-[11px] w-8 text-right shrink-0 ${textColor(r.score)}`}>
              {r.score > 0 ? '+' : ''}{r.score}
            </span>
          </div>
        )
      })}
    </div>
  )
}
