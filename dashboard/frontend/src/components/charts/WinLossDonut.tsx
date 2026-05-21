import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from 'recharts'
import { CHART, tooltipProps, emptyClass } from './chartTheme'

interface Props {
  wins: number
  losses: number
}

export function WinLossDonut({ wins, losses }: Props) {
  const total = wins + losses
  if (total === 0) {
    return <div className={`h-40 ${emptyClass}`}>No trades yet</div>
  }

  const data = [
    { name: 'Wins', value: wins },
    { name: 'Losses', value: losses },
  ]

  return (
    <div>
      <p className="text-text-secondary text-xs text-center mb-1 font-mono">
        Win rate{' '}
        <span className="text-text-primary font-semibold">
          {((wins / total) * 100).toFixed(1)}%
        </span>
      </p>
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie data={data} innerRadius="58%" outerRadius="78%" dataKey="value"
               paddingAngle={2} stroke="none" isAnimationActive={false}>
            <Cell fill={CHART.profit} />
            <Cell fill={CHART.loss} />
          </Pie>
          <Tooltip {...tooltipProps} />
          <Legend iconType="circle" iconSize={8}
                  formatter={(v) => <span className="text-text-secondary text-xs">{v}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
