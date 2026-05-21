import { useState, useEffect, useCallback } from 'react'
import clsx from 'clsx'
import { Table } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'
import { apiFetch } from '../lib/api'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { WinLossDonut } from '../components/charts/WinLossDonut'

interface Trade {
  symbol: string
  direction: 'BUY' | 'SELL'
  volume: number
  entry_price: number
  sl: number
  tp: number
  open_time: string
  status: string
}

interface HistoryResp {
  trades: Trade[]
  total: number
  win_rate: number
}

const SYMBOLS = ['ALL','EURUSD','GBPUSD','USDJPY','XAUUSD','BTCUSD','CADJPY','EURJPY']

export function History() {
  const [data, setData] = useState<HistoryResp>({ trades: [], total: 0, win_rate: 0 })
  const [symbol, setSymbol] = useState('ALL')
  const [page, setPage] = useState(1)

  const load = useCallback(() => {
    const sym = symbol !== 'ALL' ? `&symbol=${symbol}` : ''
    apiFetch(`/api/history?page=${page}&per_page=50${sym}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
  }, [symbol, page])

  useEffect(() => { load() }, [load])

  const wins   = data.trades.filter(t => t.direction === 'BUY').length
  const losses = data.trades.filter(t => t.direction === 'SELL').length

  const columns = [
    { key: 'time', header: 'Time', render: (t: Trade) => <span className="text-text-muted">{t.open_time}</span> },
    { key: 'sym',  header: 'Symbol', render: (t: Trade) => <span className="font-semibold">{t.symbol}</span> },
    { key: 'dir',  header: 'Dir', render: (t: Trade) => <Badge variant={t.direction === 'BUY' ? 'buy' : 'sell'}>{t.direction}</Badge> },
    { key: 'vol',  header: 'Lots', render: (t: Trade) => t.volume.toFixed(2), align: 'right' as const },
    { key: 'entry',header: 'Entry', render: (t: Trade) => t.entry_price.toFixed(5), align: 'right' as const },
    { key: 'sl',   header: 'SL',    render: (t: Trade) => t.sl.toFixed(5), align: 'right' as const },
    { key: 'tp',   header: 'TP',    render: (t: Trade) => t.tp.toFixed(5), align: 'right' as const },
    { key: 'status', header: 'Status', render: (t: Trade) => <span className="text-text-muted">{t.status}</span> },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Trade History" subtitle={`${data.total} orders logged`} />

      {/* Symbol filter — segmented control */}
      <div className="flex flex-wrap gap-1.5">
        {SYMBOLS.map(s => (
          <button
            key={s}
            onClick={() => { setSymbol(s); setPage(1) }}
            className={clsx(
              'px-3 h-8 rounded-lg text-xs font-mono font-medium transition-all',
              symbol === s
                ? 'bg-accent text-white shadow-glow-accent'
                : 'bg-white/[0.04] ring-1 ring-border text-text-secondary hover:text-text-primary hover:bg-white/[0.07]',
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 reveal" style={{ ['--i' as string]: 0 }}>
          <Table columns={columns} data={data.trades} keyFn={(t) => t.open_time} emptyText="No trades found" />
          {data.total > 50 && (
            <div className="flex justify-center items-center gap-2 mt-4">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="px-3 h-8 rounded-lg text-xs bg-white/[0.04] ring-1 ring-border text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:hover:text-text-secondary transition-colors">
                ← Prev
              </button>
              <span className="text-text-muted text-xs font-mono px-2">Page {page}</span>
              <button onClick={() => setPage(p => p + 1)} disabled={data.trades.length < 50}
                className="px-3 h-8 rounded-lg text-xs bg-white/[0.04] ring-1 ring-border text-text-secondary hover:text-text-primary disabled:opacity-40 disabled:hover:text-text-secondary transition-colors">
                Next →
              </button>
            </div>
          )}
        </div>
        <Panel title="Win / Loss" i={1}>
          <WinLossDonut wins={wins} losses={losses} />
        </Panel>
      </div>
    </div>
  )
}
