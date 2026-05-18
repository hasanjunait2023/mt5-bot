import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface PnLItem { label: string; value: number }

interface Props {
  data: PnLItem[]
  height?: number
}

export function PnLBarChart({ data, height = 180 }: Props) {
  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#252b3b" strokeOpacity={0.4} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: '#4a5568', fontSize: 10 }} />
        <YAxis tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={v => `$${v}`} width={50} />
        <Tooltip
          contentStyle={{ background: '#1e2330', border: '1px solid #252b3b', borderRadius: 4 }}
          labelStyle={{ color: '#8896a8', fontSize: 11 }}
          itemStyle={{ fontFamily: 'monospace', fontSize: 12 }}
          formatter={(v: number) => [`$${v.toFixed(2)}`, 'P&L']}
        />
        <Bar dataKey="value" radius={[2, 2, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.value >= 0 ? '#10b981' : '#ef4444'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
