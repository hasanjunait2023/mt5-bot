import { AreaChart, Area, ResponsiveContainer, Tooltip } from 'recharts'
import type { EquityPoint } from '../../types/trading'
import { CHART, tooltipProps } from './chartTheme'

interface Props {
  data: EquityPoint[]
  height?: number
}

export function EquityMiniChart({ data, height = 48 }: Props) {
  if (data.length < 2)
    return <div style={{ height }} className="bg-white/[0.04] rounded-md" />
  const isUp = data[data.length - 1].equity >= data[0].equity
  const color = isUp ? CHART.profit : CHART.loss

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.32} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="equity" stroke={color} strokeWidth={1.5}
              fill="url(#eqGrad)" dot={false} isAnimationActive={false} />
        <Tooltip
          {...tooltipProps}
          formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
          labelFormatter={(t: string) => t?.slice(11, 19) ?? ''}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
