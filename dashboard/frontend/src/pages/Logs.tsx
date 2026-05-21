import { useRef, useEffect, useState } from 'react'
import clsx from 'clsx'
import { useLogs } from '../hooks/useLogs'
import { LogLine } from '../components/ui/LogLine'
import { PageHeader } from '../components/ui/PageHeader'
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

  const activeLevel: Record<LevelFilter, string> = {
    ALL:     'bg-accent text-white shadow-glow-accent',
    INFO:    'bg-accent text-white shadow-glow-accent',
    WARNING: 'bg-warning/20 text-warning ring-1 ring-warning/40',
    ERROR:   'bg-loss/20 text-loss ring-1 ring-loss/40',
  }

  return (
    <div className="flex flex-col h-full space-y-4">
      <PageHeader
        title="Live Logs"
        subtitle={`${filtered.length} lines · streaming in real time`}
      />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1.5">
          {LEVELS.map(l => (
            <button
              key={l}
              onClick={() => setLevel(l)}
              className={clsx(
                'px-3 h-8 rounded-lg text-xs font-semibold transition-all',
                level === l
                  ? activeLevel[l]
                  : 'bg-white/[0.04] ring-1 ring-border text-text-secondary hover:text-text-primary hover:bg-white/[0.07]',
              )}
            >
              {l}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search logs…"
          className="flex-1 min-w-[200px] h-8 bg-white/[0.04] ring-1 ring-border rounded-lg px-3 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-accent font-mono transition-shadow"
        />
        <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none px-2">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)}
            className="w-3.5 h-3.5 accent-accent" />
          Auto-scroll
        </label>
      </div>

      {/* Log stream */}
      <div className="glass flex-1 p-4 overflow-y-auto min-h-[400px] reveal">
        {filtered.length === 0 ? (
          <p className="text-text-muted text-sm text-center mt-10">No log lines match your filter</p>
        ) : (
          filtered.map((e: LogEntry, i) => <LogLine key={i} entry={e} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
