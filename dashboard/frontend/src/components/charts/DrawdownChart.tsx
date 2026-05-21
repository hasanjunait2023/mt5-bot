import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { CHART, tooltipProps, emptyClass } from './chartTheme'

interface DDPoint { t: string; drawdown: number }

interface Props {
  data: DDPoint[]
}

export function DrawdownChart({ data }: Props) {
  if (data.length < 2) {
    return <div className={`h-40 ${emptyClass}`}>No drawdown data yet</div>
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={CHART.loss} stopOpacity={0.42} />
            <stop offset="95%" stopColor={CHART.loss} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="t" tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={t => t?.slice(11, 16) ?? ''}
               interval="preserveStartEnd" axisLine={{ stroke: CHART.grid }} tickLine={false} />
        <YAxis tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={v => `${v}%`} width={44} reversed
               axisLine={false} tickLine={false} />
        <Tooltip
          {...tooltipProps}
          itemStyle={{ ...tooltipProps.itemStyle, color: CHART.loss }}
          formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
        />
        <Area type="monotone" dataKey="drawdown" stroke={CHART.loss} strokeWidth={1.5}
              fill="url(#ddGrad)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
