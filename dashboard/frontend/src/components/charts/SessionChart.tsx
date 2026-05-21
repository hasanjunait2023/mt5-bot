import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { CHART, tooltipProps, emptyClass } from './chartTheme'

interface Props {
  data: Array<{ session: string; avg_pnl: number; trades: number }>
}

export function SessionChart({ data }: Props) {
  if (!data.length) {
    return <div className={`h-40 ${emptyClass}`}>No session data</div>
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="session" tick={{ fill: CHART.axisStrong, fontSize: 11 }}
               axisLine={{ stroke: CHART.grid }} tickLine={false} />
        <YAxis tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={v => `$${v}`} width={44}
               axisLine={false} tickLine={false} />
        <Tooltip
          {...tooltipProps}
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          formatter={(v: number, name: string) => [name === 'avg_pnl' ? `$${v.toFixed(2)}` : v, name === 'avg_pnl' ? 'Avg P&L' : 'Trades']}
        />
        <Bar dataKey="avg_pnl" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={d.avg_pnl >= 0 ? CHART.profit : CHART.loss} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
