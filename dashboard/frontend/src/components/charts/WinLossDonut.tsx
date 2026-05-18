import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from 'recharts'

interface Props {
  wins: number
  losses: number
}

export function WinLossDonut({ wins, losses }: Props) {
  const total = wins + losses
  if (total === 0) {
    return (
      <div className="h-40 flex items-center justify-center text-text-muted text-sm">No trades yet</div>
    )
  }

  const data = [
    { name: 'Wins', value: wins },
    { name: 'Losses', value: losses },
  ]

  return (
    <div>
      <p className="text-text-muted text-xs text-center mb-1 font-mono">
        Win rate {((wins / total) * 100).toFixed(1)}%
      </p>
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie data={data} innerRadius="55%" outerRadius="75%" dataKey="value" isAnimationActive={false}>
            <Cell fill="#10b981" />
            <Cell fill="#ef4444" />
          </Pie>
          <Tooltip
            contentStyle={{ background: '#1e2330', border: '1px solid #252b3b', borderRadius: 4 }}
            itemStyle={{ color: '#e8ecf4', fontFamily: 'monospace', fontSize: 12 }}
          />
          <Legend iconType="circle" iconSize={8}
                  formatter={(v) => <span className="text-text-secondary text-xs">{v}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
