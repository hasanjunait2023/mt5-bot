import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { CHART, tooltipProps } from './chartTheme'

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
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: CHART.axis, fontSize: 10 }}
               axisLine={{ stroke: CHART.grid }} tickLine={false} />
        <YAxis tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={v => `$${v}`} width={50}
               axisLine={false} tickLine={false} />
        <Tooltip
          {...tooltipProps}
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          formatter={(v: number) => [`$${v.toFixed(2)}`, 'P&L']}
        />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.value >= 0 ? CHART.profit : CHART.loss} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
