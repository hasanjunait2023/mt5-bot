import { createContext, useContext, type ReactNode } from 'react'
import type { TraderState } from '../types/trading'
import { useTraderState } from '../hooks/useTraderState'

const TradingContext = createContext<TraderState | null>(null)

export function TradingProvider({ children }: { children: ReactNode }) {
  const state = useTraderState()
  return <TradingContext.Provider value={state}>{children}</TradingContext.Provider>
}

export function useTrading(): TraderState {
  const ctx = useContext(TradingContext)
  if (!ctx) throw new Error('useTrading must be inside TradingProvider')
  return ctx
}
