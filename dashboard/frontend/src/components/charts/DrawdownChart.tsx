import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

interface DDPoint { t: string; drawdown: number }

interface Props {
  data: DDPoint[]
}

export function DrawdownChart({ data }: Props) {
  if (data.length < 2) {
    return (
      <div className="h-40 bg-bg-elevated rounded-lg flex items-center justify-center text-text-muted text-sm">
        No drawdown data yet
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.4} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#252b3b" strokeOpacity={0.4} />
        <XAxis dataKey="t" tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={t => t?.slice(11, 16) ?? ''}
               interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#4a5568', fontSize: 10 }} tickFormatter={v => `${v}%`} width={44} reversed />
        <Tooltip
          contentStyle={{ background: '#1e2330', border: '1px solid #252b3b', borderRadius: 4 }}
          labelStyle={{ color: '#8896a8', fontSize: 11 }}
          itemStyle={{ color: '#ef4444', fontFamily: 'monospace', fontSize: 12 }}
          formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
        />
        <Area type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={1.5}
              fill="url(#ddGrad)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
