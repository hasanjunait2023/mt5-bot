import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { EquityPoint } from '../../types/trading'

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
            <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#252b3b" strokeOpacity={0.4} />
        <XAxis dataKey="t" tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={t => t?.slice(11, 16) ?? ''}
               interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={v => `$${v}`} width={60} />
        <Tooltip
          contentStyle={{ background: '#1e2330', border: '1px solid #252b3b', borderRadius: 4 }}
          labelStyle={{ color: '#8896a8', fontSize: 11 }}
          itemStyle={{ color: '#e8ecf4', fontFamily: 'monospace', fontSize: 12 }}
          formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
        />
        <Area type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={2}
              fill="url(#eqFull)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-60 bg-bg-elevated rounded-lg flex items-center justify-center text-text-muted text-sm">
      No {label} data yet
    </div>
  )
}
