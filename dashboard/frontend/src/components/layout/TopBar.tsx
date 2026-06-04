import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTrading } from '../../contexts/TradingContext'
import { useConnectionState } from '../../hooks/useWebSocket'
import { SessionClock } from '../ui/SessionClock'

export function TopBar() {
  const { trader_running, mt5_connected, nvidia_api_alive, account } = useTrading()
  const [connState, setConnState] = useState<string>('closed')

  useConnectionState(setConnState)

  const wsColor =
    connState === 'open' ? 'bg-profit' : connState === 'connecting' ? 'bg-warning' : 'bg-loss'

  return (
    <header className="h-14 shrink-0 flex items-center justify-between gap-3 px-3 md:px-6
                       bg-bg-surface/70 backdrop-blur-xl border-b border-border shadow-topbar">
      {/* Brand + account identity */}
      <Link
        to="/"
        className="flex items-center gap-2.5 min-w-0 rounded-xl -ml-1 pl-1 pr-2 py-1
                   hover:bg-white/[0.03] transition-colors"
      >
        <div className="relative grid place-items-center w-8 h-8 rounded-xl
                        bg-gradient-to-br from-accent to-accent-dim shadow-glow-accent
                        ring-1 ring-white/15">
          <span className="text-white text-sm font-bold leading-none">M</span>
          <span className="absolute inset-x-1 top-0.5 h-px bg-white/30 rounded-full" />
        </div>
        <div className="leading-tight min-w-0">
          <div className="text-text-primary font-semibold text-sm tracking-tight">
            MT5&nbsp;Terminal
          </div>
          {account.server && account.server !== '—' && (
            <div className="text-text-muted text-[11px] font-mono truncate">
              #{account.login} · {account.server}
            </div>
          )}
        </div>
      </Link>

      {/* Live status cluster */}
      <div className="flex items-center gap-2 md:gap-2.5 shrink-0">
        <div className="hidden sm:block">
          <SessionClock />
        </div>

        {/* Connectivity — WS + AI in one segmented pill for a cohesive read */}
        <div className="flex items-center h-8 px-2.5 gap-2.5 rounded-full bg-white/[0.04] ring-1 ring-border">
          <span className="flex items-center gap-1.5" title={`WebSocket: ${connState}`}>
            <span className="relative flex w-2 h-2">
              {connState === 'connecting' && (
                <span className="absolute inset-0 rounded-full bg-warning animate-pulse2" />
              )}
              <span className={`relative w-2 h-2 rounded-full ${wsColor}`} />
            </span>
            <span className="text-text-secondary text-[11px] font-semibold tracking-wide">WS</span>
          </span>
          {nvidia_api_alive !== undefined && (
            <>
              <span className="w-px h-3.5 bg-border" />
              <span className="flex items-center gap-1.5" title={`AI engine: ${nvidia_api_alive ? 'alive' : 'down'}`}>
                <span className={`w-2 h-2 rounded-full ${nvidia_api_alive ? 'bg-profit' : 'bg-loss'}`} />
                <span className="text-text-secondary text-[11px] font-semibold tracking-wide">AI</span>
              </span>
            </>
          )}
        </div>

        {/* Trader run state */}
        <div
          className={`flex items-center gap-1.5 pl-2.5 pr-3 h-8 rounded-full text-[11px] font-bold tracking-wide
            ${trader_running
              ? 'text-profit bg-profit/10 ring-1 ring-profit/30'
              : 'text-loss bg-loss/10 ring-1 ring-loss/25'}`}
        >
          <span className="relative flex w-1.5 h-1.5">
            {trader_running && (
              <span className="absolute inline-flex w-full h-full rounded-full bg-profit opacity-60 animate-glow-ring" />
            )}
            <span
              className={`relative w-1.5 h-1.5 rounded-full ${trader_running ? 'bg-profit' : 'bg-loss'}`}
            />
          </span>
          {trader_running ? 'LIVE' : 'OFFLINE'}
        </div>

        {!mt5_connected && trader_running && (
          <span className="hidden md:inline text-warning text-[11px] font-medium px-2 py-1
                           rounded-md bg-warning/10 ring-1 ring-warning/25">
            MT5 Disconnected
          </span>
        )}
      </div>
    </header>
  )
}
