import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { EquityPoint } from '../../types/trading'
import { CHART, tooltipProps, emptyClass } from './chartTheme'

interface Props {
  data: EquityPoint[]
}

export function EquityCurveChart({ data }: Props) {
  if (data.length < 2) return <EmptyChart label="Equity" />

  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="eqFull" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={CHART.accent} stopOpacity={0.32} />
            <stop offset="95%" stopColor={CHART.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="t" tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={t => t?.slice(11, 16) ?? ''}
               interval="preserveStartEnd" axisLine={{ stroke: CHART.grid }} tickLine={false} />
        <YAxis tick={{ fill: CHART.axis, fontSize: 10 }} tickFormatter={v => `$${v}`} width={60}
               axisLine={false} tickLine={false} />
        <Tooltip {...tooltipProps} formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']} />
        <Area type="monotone" dataKey="equity" stroke={CHART.accent} strokeWidth={2}
              fill="url(#eqFull)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function EmptyChart({ label }: { label: string }) {
  return <div className={`h-60 ${emptyClass}`}>No {label} data yet</div>
}
