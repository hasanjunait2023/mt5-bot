import { useRef, useEffect, useState } from 'react'
import { useLogs } from '../hooks/useLogs'
import { LogLine } from '../components/ui/LogLine'
import type { LogEntry } from '../types/trading'

const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'] as const
type LevelFilter = typeof LEVELS[number]

export function Logs() {
  const allLines = useLogs()
  const [level, setLevel] = useState<LevelFilter>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)

  const filtered = allLines.filter(l => {
    const levelOk = level === 'ALL' || l.level === level
    const searchOk = !search || l.raw.toLowerCase().includes(search.toLowerCase())
    return levelOk && searchOk
  })

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [filtered.length, autoScroll])

  const levelColors: Record<LevelFilter, string> = {
    ALL:     'bg-bg-elevated text-text-primary',
    INFO:    'bg-bg-elevated text-text-primary',
    WARNING: 'bg-warning/20 text-warning',
    ERROR:   'bg-loss/20 text-loss',
  }

  return (
    <div className="flex flex-col h-full space-y-3">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Live Logs</h1>
        <p className="text-text-muted text-sm">{filtered.length} lines — streaming in real time</p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {LEVELS.map(l => (
            <button key={l} onClick={() => setLevel(l)}
              className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors ${
                level === l ? levelColors[l] + ' ring-1 ring-inset ring-current' : 'bg-bg-elevated text-text-secondary hover:text-text-primary'
              }`}
            >{l}</button>
          ))}
        </div>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search logs…"
          className="flex-1 min-w-[180px] bg-bg-elevated border border-border rounded px-3 py-1 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-accent font-mono"
        />
        <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)}
            className="w-3 h-3 accent-accent" />
          Auto-scroll
        </label>
      </div>

      {/* Log stream */}
      <div className="flex-1 bg-bg-surface border border-border rounded-lg p-3 overflow-y-auto min-h-[400px]">
        {filtered.length === 0 ? (
          <p className="text-text-muted text-sm text-center mt-8">No log lines match your filter</p>
        ) : (
          filtered.map((e: LogEntry, i) => <LogLine key={i} entry={e} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
