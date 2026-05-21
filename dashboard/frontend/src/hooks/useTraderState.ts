import { useState, useEffect } from 'react'
import type { TraderState } from '../types/trading'
import { useWebSocket } from './useWebSocket'
import { apiFetch } from '../lib/api'

const INITIAL: TraderState = {
  timestamp: null,
  trader_running: false,
  mt5_connected: false,
  account: {
    login: 0, server: '—', balance: 0, equity: 0,
    margin: 0, free_margin: 0, daily_pnl: 0,
    daily_dd_pct: 0, total_dd_pct: 0, start_balance: 0,
  },
  positions: [],
  equity_history: [],
  daily_trades: {},
  last_signals: {},
  symbols: [],
  agents: {
    strategy_researcher: { total_strategies: 0, successful: 0, failed: 0, last_updated: null, symbols: [] },
    performance_optimizer: { total_adaptations: 0, last_adaptation: null, monthly_cycles: 0 },
    execution_manager: { daily_records: 0, last_day: null },
  },
}

export function useTraderState(): TraderState {
  const [state, setState] = useState<TraderState>(INITIAL)

  useWebSocket('state', (data) => {
    setState(data as TraderState)
  })

  useEffect(() => {
    apiFetch('/api/overview')
      .then(r => r.json())
      .then(data => setState(prev => ({ ...prev, ...data })))
      .catch(() => {})
  }, [])

  return state
}
