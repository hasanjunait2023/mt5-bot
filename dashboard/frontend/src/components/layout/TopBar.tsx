import { useState, useEffect } from 'react'
import { useTrading } from '../../contexts/TradingContext'
import { useConnectionState } from '../../hooks/useWebSocket'

export function TopBar() {
  const { trader_running, mt5_connected, nvidia_api_alive, account } = useTrading()
  const [connState, setConnState] = useState<string>('closed')
  const [clock, setClock] = useState('')

  useConnectionState(setConnState)

  useEffect(() => {
    const tick = () => setClock(new Date().toUTCString().slice(17, 25) + ' UTC')
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const wsColor  = connState === 'open' ? 'bg-profit' : connState === 'connecting' ? 'bg-warning' : 'bg-loss'
  const botColor = trader_running ? 'text-profit' : 'text-loss'

  return (
    <div className="h-12 bg-bg-surface border-b border-border flex items-center justify-between px-4 shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-text-primary font-semibold text-sm tracking-wide">MT5 Dashboard</span>
        {account.server && account.server !== '—' && (
          <span className="text-text-muted text-xs font-mono">#{account.login} @ {account.server}</span>
        )}
      </div>
      <div className="flex items-center gap-4">
        <span className="text-text-muted text-xs font-mono">{clock}</span>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${wsColor} ${connState === 'connecting' ? 'animate-pulse2' : ''}`} />
          <span className="text-text-secondary text-xs">WS</span>
        </div>
        <div className={`text-xs font-semibold ${botColor}`}>
          {trader_running ? '● LIVE' : '○ OFFLINE'}
        </div>
        {!mt5_connected && trader_running && (
          <span className="text-warning text-xs">MT5 Disconnected</span>
        )}
        {nvidia_api_alive !== undefined && (
          <div className="flex items-center gap-1.5" title="NVIDIA AI API">
            <div className={`w-2 h-2 rounded-full ${nvidia_api_alive ? 'bg-profit' : 'bg-loss'}`} />
            <span className="text-text-secondary text-xs">AI</span>
          </div>
        )}
      </div>
    </div>
  )
}
