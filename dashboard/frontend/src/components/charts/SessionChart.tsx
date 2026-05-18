import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface Props {
  data: Array<{ session: string; avg_pnl: number; trades: number }>
}

export function SessionChart({ data }: Props) {
  if (!data.length) {
    return (
      <div className="h-40 flex items-center justify-center text-text-muted text-sm">No session data</div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#252b3b" strokeOpacity={0.4} vertical={false} />
        <XAxis dataKey="session" tick={{ fill: '#8896a8', fontSize: 11 }} />
        <YAxis tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={v => `$${v}`} width={44} />
        <Tooltip
          contentStyle={{ background: '#1e2330', border: '1px solid #252b3b', borderRadius: 4 }}
          itemStyle={{ fontFamily: 'monospace', fontSize: 12, color: '#e8ecf4' }}
          formatter={(v: number, name: string) => [name === 'avg_pnl' ? `$${v.toFixed(2)}` : v, name === 'avg_pnl' ? 'Avg P&L' : 'Trades']}
        />
        <Bar dataKey="avg_pnl" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={d.avg_pnl >= 0 ? '#10b981' : '#ef4444'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
