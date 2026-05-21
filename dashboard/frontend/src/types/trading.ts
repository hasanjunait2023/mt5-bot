export interface Account {
  login: number
  server: string
  balance: number
  equity: number
  margin: number
  free_margin: number
  daily_pnl: number
  daily_dd_pct: number
  total_dd_pct: number
  start_balance: number
}

export interface Position {
  ticket: number
  symbol: string
  direction: 'BUY' | 'SELL'
  volume: number
  entry_price: number
  current_price: number
  sl: number
  tp: number
  profit: number
  swap: number
  open_time: number
  magic: number
  // computed by backend
  duration_mins?: number
  pips_to_sl?: number
  pips_to_tp?: number
  unrealized_pct?: number
}

export interface EquityPoint {
  t: string
  equity: number
}

export interface LogEntry {
  timestamp: string
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
  message: string
  raw: string
}

export interface SignalInfo {
  direction: 'BUY' | 'SELL' | null
  bar_time: string | null
}

export interface StrategyResearcher {
  total_strategies: number
  successful: number
  failed: number
  last_updated: string | null
  symbols: string[]
  symbol_stats?: Record<string, {
    successful_patterns: number
    failed_patterns: number
    regime_performance: Record<string, unknown>
  }>
}

export interface PerformanceOptimizer {
  total_adaptations: number
  last_adaptation: Record<string, unknown> | null
  monthly_cycles: number
}

export interface ExecutionManager {
  daily_records: number
  last_day: Record<string, unknown> | null
}

export interface Agents {
  strategy_researcher: StrategyResearcher
  performance_optimizer: PerformanceOptimizer
  execution_manager: ExecutionManager
}

export interface TraderState {
  timestamp: string | null
  trader_running: boolean
  mt5_connected: boolean
  nvidia_api_alive?: boolean
  account: Account
  positions: Position[]
  equity_history: EquityPoint[]
  daily_trades: Record<string, number>
  last_signals: Record<string, SignalInfo>
  symbols: string[]
  agents: Agents
  recent_events?: LogEntry[]
}

export interface SignalEvent {
  id: string
  ts: string
  type: 'alignment' | 'cross' | 'touch'
  symbol: string
  side: 'BUY' | 'SELL'
  timeframe: string
  price: number
  ema9: number
  ema15: number
  ema200: number
  note: string
  chart_path?: string | null
  chart_b64?: string
  detect_ms?: number
}

export type WSMessage =
  | { type: 'connected'; data: { server_time: string } }
  | { type: 'state';     data: TraderState }
  | { type: 'log';       data: LogEntry }
  | { type: 'signal';    data: SignalEvent }
