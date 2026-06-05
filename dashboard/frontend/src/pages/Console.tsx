import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Icon } from '../components/ui/Icon'
import {
  consoleFetch, consoleWsUrl, getConsoleToken, setConsoleToken, clearConsoleToken,
} from '../lib/console'

// ── wire types ────────────────────────────────────────────────────────────
type Ev =
  | { type: 'ready'; cwd: string }
  | { type: 'assistant'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool_use'; id: string; name: string; input: any }
  | { type: 'tool_result'; tool_use_id: string; content: string; is_error: boolean }
  | { type: 'system'; subtype: string; session_id?: string }
  | { type: 'result'; session_id?: string; is_error: boolean; cost_usd?: number; result?: string }
  | { type: 'session'; session_id: string }
  | { type: 'turn_end' } | { type: 'aborted' } | { type: 'error'; message: string }
  | { type: 'user'; text: string }

type Item =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; text: string }
  | { kind: 'thinking'; text: string }
  | { kind: 'tool'; id: string; name: string; input: any; result?: string; isError?: boolean }
  | { kind: 'result'; cost?: number; isError: boolean }
  | { kind: 'error'; text: string }

type Session = { session_id: string; title: string; message_count?: number }
type Status = { state: 'loading' | 'ok' | 'disabled' | 'forbidden' | 'nosdk'; cwd?: string }

const ACTIVE_KEY = 'mt5_console_active'

function eventsToItems(evs: Ev[]): Item[] {
  const items: Item[] = []
  for (const e of evs) {
    if (e.type === 'user') items.push({ kind: 'user', text: e.text })
    else if (e.type === 'assistant') items.push({ kind: 'assistant', text: e.text })
    else if (e.type === 'thinking') items.push({ kind: 'thinking', text: e.text })
    else if (e.type === 'tool_use') items.push({ kind: 'tool', id: e.id, name: e.name, input: e.input })
    else if (e.type === 'tool_result') {
      const t = [...items].reverse().find(i => i.kind === 'tool' && (i as any).id === e.tool_use_id) as any
      if (t) { t.result = e.content; t.isError = e.is_error }
    } else if (e.type === 'result') items.push({ kind: 'result', cost: e.cost_usd ?? undefined, isError: e.is_error })
    else if (e.type === 'error') items.push({ kind: 'error', text: e.message })
  }
  return items
}

// ── page ────────────────────────────────────────────────────────────────
export function Console() {
  const [status, setStatus] = useState<Status>({ state: 'loading' })
  const [authed, setAuthed] = useState(!!getConsoleToken())
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [running, setRunning] = useState(false)
  const [connected, setConnected] = useState(false)
  const [input, setInput] = useState('')
  const [atBottom, setAtBottom] = useState(true)
  const [navOpen, setNavOpen] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const threadRef = useRef<HTMLDivElement | null>(null)
  const taRef = useRef<HTMLTextAreaElement | null>(null)
  sessionIdRef.current = sessionId

  // probe status
  useEffect(() => {
    consoleFetch('/api/console/status')
      .then(async r => {
        if (r.status === 404) return setStatus({ state: 'disabled' })
        if (r.status === 403) return setStatus({ state: 'forbidden' })
        const d = await r.json()
        setStatus({ state: d.sdk ? 'ok' : 'nosdk', cwd: d.cwd })
      })
      .catch(() => setStatus({ state: 'forbidden' }))
  }, [])

  const loadSessions = useCallback(() => {
    consoleFetch('/api/console/sessions')
      .then(r => (r.ok ? r.json() : { sessions: [] }))
      .then(d => setSessions(d.sessions || []))
      .catch(() => {})
  }, [])

  const loadHistory = useCallback(async (id: string) => {
    const r = await consoleFetch(`/api/console/sessions/${id}/messages`)
    if (r.ok) { const d = await r.json(); setItems(eventsToItems(d.events || [])) }
  }, [])

  // restore the last-open chat across navigation (the fix for "chat lost")
  useEffect(() => {
    if (!authed || status.state !== 'ok') return
    loadSessions()
    const saved = (() => { try { return localStorage.getItem(ACTIVE_KEY) } catch { return null } })()
    if (saved) { setSessionId(saved); loadHistory(saved) }
  }, [authed, status.state, loadSessions, loadHistory])

  const setActive = (id: string | null) => {
    setSessionId(id)
    try { id ? localStorage.setItem(ACTIVE_KEY, id) : localStorage.removeItem(ACTIVE_KEY) } catch { /* */ }
  }

  const apply = useCallback((e: Ev) => {
    setItems(prev => {
      if (e.type === 'tool_result') {
        const next = [...prev]
        for (let i = next.length - 1; i >= 0; i--) {
          const it = next[i]
          if (it.kind === 'tool' && it.id === e.tool_use_id) { next[i] = { ...it, result: e.content, isError: e.is_error }; return next }
        }
        return prev
      }
      const mapped = eventsToItems([e])
      return mapped.length ? [...prev, ...mapped] : prev
    })
  }, [])

  // websocket
  useEffect(() => {
    if (!authed || status.state !== 'ok') return
    let closed = false
    const connect = () => {
      const ws = new WebSocket(consoleWsUrl())
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => { setConnected(false); setRunning(false); if (!closed) setTimeout(connect, 1500) }
      ws.onmessage = ev => {
        let m: Ev; try { m = JSON.parse(ev.data) } catch { return }
        if (m.type === 'session') { setActive(m.session_id); loadSessions(); return }
        if (m.type === 'turn_end') { setRunning(false); return }
        if (m.type === 'ready') return
        if (m.type === 'aborted') { apply({ type: 'error', message: 'Aborted.' }); return }
        apply(m)
      }
    }
    connect()
    return () => { closed = true; wsRef.current?.close() }
  }, [authed, status.state, apply, loadSessions])

  // autoscroll only when already near the bottom
  useLayoutEffect(() => {
    if (atBottom) threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight })
  }, [items, running])

  const onThreadScroll = () => {
    const el = threadRef.current; if (!el) return
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }
  const scrollDown = () => threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' })

  // auto-grow composer
  useEffect(() => {
    const ta = taRef.current; if (!ta) return
    ta.style.height = '0px'
    ta.style.height = Math.min(ta.scrollHeight, 220) + 'px'
  }, [input])

  const send = () => {
    const text = input.trim()
    if (!text || running || wsRef.current?.readyState !== WebSocket.OPEN) return
    setItems(prev => [...prev, { kind: 'user', text }])
    wsRef.current.send(JSON.stringify({ type: 'user', text, session_id: sessionIdRef.current }))
    setRunning(true); setInput(''); setAtBottom(true)
  }
  const stop = () => wsRef.current?.send(JSON.stringify({ type: 'stop' }))
  const newChat = () => { setActive(null); setItems([]); setNavOpen(false); taRef.current?.focus() }
  const openSession = async (id: string) => { setActive(id); setItems([]); setNavOpen(false); await loadHistory(id) }
  const deleteSession = async (id: string) => {
    await consoleFetch(`/api/console/sessions/${id}`, { method: 'DELETE' })
    if (id === sessionId) newChat()
    loadSessions()
  }
  const renameSession = async (id: string, title: string) => {
    await consoleFetch(`/api/console/sessions/${id}/rename`, { method: 'POST', body: JSON.stringify({ title }) })
    loadSessions()
  }

  // ── gates ───────────────────────────────────────────────────────────
  if (status.state === 'loading')
    return <div className="grid place-items-center min-h-[50vh] text-text-muted animate-pulse">Connecting…</div>
  if (status.state === 'disabled' || status.state === 'forbidden' || status.state === 'nosdk')
    return <GateMsg state={status.state} />
  if (!authed) return <ConsoleLogin onAuthed={() => setAuthed(true)} />

  // ── main ────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-[calc(100dvh-7.5rem)] min-h-[460px]">
      {/* header */}
      <div className="flex items-center gap-3 mb-3 shrink-0">
        <button onClick={() => setNavOpen(o => !o)} className="lg:hidden grid place-items-center w-9 h-9 rounded-xl glass">
          <Icon name="bots" size={16} />
        </button>
        <div className="grid place-items-center w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-accent-dim shadow-glow-accent shrink-0">
          <Icon name="terminal" size={17} className="text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-lg md:text-xl font-bold tracking-tight text-text-primary leading-none">Claude Console</h1>
          <p className="text-[11px] text-text-muted font-mono truncate mt-1">{status.cwd || 'Claude Code'}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`hidden sm:flex items-center gap-1.5 text-[11px] font-semibold px-2.5 h-7 rounded-full ring-1 ${connected ? 'text-profit bg-profit/10 ring-profit/25' : 'text-warning bg-warning/10 ring-warning/25'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-profit animate-pulse2' : 'bg-warning'}`} />
            {connected ? 'live' : 'reconnecting'}
          </span>
          <span className="hidden md:grid place-items-center text-[10px] font-bold tracking-wide text-warning bg-warning/10 ring-1 ring-warning/30 px-2.5 h-7 rounded-full">AUTONOMOUS</span>
          <button onClick={() => { clearConsoleToken(); setAuthed(false) }}
                  title="Lock console"
                  className="grid place-items-center w-7 h-7 rounded-full text-text-muted hover:text-text-primary hover:bg-tint/[0.06] ring-1 ring-border">
            <Icon name="settings" size={13} />
          </button>
        </div>
      </div>

      {/* body: sessions + chat */}
      <div className="grid grid-cols-1 lg:grid-cols-[252px_minmax(0,1fr)] gap-4 flex-1 min-h-0">
        {/* sessions */}
        <aside className={`glass p-3 flex-col min-h-0 ${navOpen ? 'flex' : 'hidden'} lg:flex`}>
          <button onClick={newChat}
                  className="w-full flex items-center justify-center gap-2 h-9 rounded-xl bg-accent text-white text-sm font-semibold hover:bg-accent-dim transition-colors shrink-0">
            <span className="text-base leading-none">+</span> New chat
          </button>
          <div className="mt-3 -mx-1 px-1 space-y-0.5 overflow-y-auto min-h-0">
            {sessions.map(s => (
              <SessionRow key={s.session_id} s={s} active={s.session_id === sessionId}
                          onOpen={() => openSession(s.session_id)} onDelete={() => deleteSession(s.session_id)}
                          onRename={t => renameSession(s.session_id, t)} />
            ))}
            {sessions.length === 0 && <p className="text-text-muted text-xs px-2 py-3">No sessions yet</p>}
          </div>
        </aside>

        {/* chat */}
        <section className="glass relative flex flex-col min-h-0 min-w-0 overflow-hidden">
          <div ref={threadRef} onScroll={onThreadScroll} className="flex-1 min-h-0 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-4 md:px-6 py-5 space-y-4">
              {items.length === 0 && <EmptyState />}
              {items.map((it, i) => <ThreadItem key={i} item={it} />)}
              {running && (
                <div className="flex items-center gap-2 text-text-muted text-xs">
                  <span className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse2" />
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse2" style={{ animationDelay: '0.2s' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse2" style={{ animationDelay: '0.4s' }} />
                  </span>
                  working…
                </div>
              )}
            </div>
          </div>

          {!atBottom && (
            <button onClick={scrollDown}
                    className="absolute bottom-24 left-1/2 -translate-x-1/2 grid place-items-center w-9 h-9 rounded-full bg-bg-elevated ring-1 ring-border shadow-card text-text-secondary hover:text-text-primary">
              ↓
            </button>
          )}

          {/* composer */}
          <div className="shrink-0 border-t border-border p-3 bg-bg-surface/60">
            <div className="mx-auto w-full max-w-3xl">
              <div className="flex items-end gap-2 rounded-2xl bg-bg-elevated ring-1 ring-border focus-within:ring-accent/50 transition-shadow px-2 py-1.5">
                <textarea
                  ref={taRef} value={input} onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send() } }}
                  placeholder="Ask Claude Code to build, fix, deploy…"
                  rows={1}
                  className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-text-primary placeholder:text-text-muted outline-none min-h-0"
                />
                {running
                  ? <button onClick={stop} className="h-9 px-4 rounded-xl bg-loss/15 text-loss ring-1 ring-loss/30 text-sm font-semibold hover:bg-loss/25 shrink-0">Stop</button>
                  : <button onClick={send} disabled={!input.trim() || !connected}
                            className="h-9 px-4 rounded-xl bg-accent text-white text-sm font-semibold hover:bg-accent-dim disabled:opacity-40 disabled:cursor-not-allowed shrink-0">Send</button>}
              </div>
              <p className="text-[10px] text-text-muted mt-1.5 px-2 flex items-center gap-2">
                <kbd className="font-mono">⌘/Ctrl+↵</kbd> to send · runs autonomously on the live VPS
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

// ── session row (rename / delete) ──────────────────────────────────────
function SessionRow({ s, active, onOpen, onDelete, onRename }:
  { s: Session; active: boolean; onOpen: () => void; onDelete: () => void; onRename: (t: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(s.title)
  if (editing)
    return (
      <input autoFocus value={val} onChange={e => setVal(e.target.value)}
             onBlur={() => { setEditing(false); if (val.trim() && val !== s.title) onRename(val.trim()) }}
             onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') { setVal(s.title); setEditing(false) } }}
             className="w-full bg-bg-elevated rounded-lg px-2 py-1.5 text-[13px] text-text-primary outline-none ring-1 ring-accent/50" />
    )
  return (
    <div onClick={onOpen} onDoubleClick={() => setEditing(true)}
         className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] cursor-pointer transition-colors ${active ? 'bg-accent/[0.12] text-text-primary ring-1 ring-accent/20' : 'text-text-secondary hover:bg-tint/[0.05]'}`}>
      <span className="flex-1 truncate">{s.title || 'Untitled'}</span>
      <button onClick={e => { e.stopPropagation(); setEditing(true) }} title="Rename"
              className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-text-primary px-1 text-xs">✎</button>
      <button onClick={e => { e.stopPropagation(); onDelete() }} title="Delete"
              className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-loss px-0.5 text-xs">✕</button>
    </div>
  )
}

// ── thread items ───────────────────────────────────────────────────────
function ThreadItem({ item }: { item: Item }) {
  if (item.kind === 'user')
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] min-w-0 rounded-2xl rounded-br-md bg-accent text-white px-4 py-2.5 text-sm whitespace-pre-wrap break-words shadow-sm">{item.text}</div>
      </div>
    )
  if (item.kind === 'assistant')
    return <div className="min-w-0 text-[14px] text-text-primary leading-relaxed"><Markdown text={item.text} /></div>
  if (item.kind === 'thinking') return <Thinking text={item.text} />
  if (item.kind === 'error')
    return <div className="text-sm text-loss bg-loss/10 ring-1 ring-loss/25 rounded-xl px-3 py-2">{item.text}</div>
  if (item.kind === 'result')
    return (
      <div className="flex items-center gap-3 text-[11px] text-text-muted py-1">
        <span className="hairline flex-1" />
        {item.isError ? <span className="text-loss">finished with error</span> : <span>done{item.cost ? ` · $${item.cost.toFixed(4)}` : ''}</span>}
        <span className="hairline flex-1" />
      </div>
    )
  return <ToolCard item={item} />
}

function Thinking({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-w-0">
      <button onClick={() => setOpen(o => !o)} className="text-[11px] text-text-muted italic hover:text-text-secondary flex items-center gap-1">
        <span>{open ? '▾' : '▸'}</span> thinking
      </button>
      {open && <div className="mt-1 text-xs text-text-muted italic whitespace-pre-wrap break-words border-l-2 border-border pl-3">{text}</div>}
    </div>
  )
}

const TOOL_LABEL: Record<string, string> = {
  Bash: 'ran', Edit: 'edited', Write: 'wrote', Read: 'read', Grep: 'searched', Glob: 'globbed', TodoWrite: 'planned',
}

function ToolCard({ item }: { item: Extract<Item, { kind: 'tool' }> }) {
  const [open, setOpen] = useState(false)
  const inp = item.input || {}
  const isBash = item.name === 'Bash', isEdit = item.name === 'Edit', isWrite = item.name === 'Write'
  const summary = isBash ? inp.command
    : isEdit || isWrite || item.name === 'Read' ? (inp.file_path || inp.path || '')
    : item.name === 'Grep' || item.name === 'Glob' ? (inp.pattern || '')
    : JSON.stringify(inp).slice(0, 140)
  return (
    <div className="min-w-0 rounded-xl ring-1 ring-border bg-bg-elevated/50 overflow-hidden">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-2 px-3 py-2 text-left min-w-0">
        <span className="text-[10px] font-bold uppercase tracking-wide text-accent bg-accent/10 ring-1 ring-accent/20 px-1.5 py-0.5 rounded shrink-0">{TOOL_LABEL[item.name] || item.name}</span>
        <span className="flex-1 min-w-0 truncate font-mono text-xs text-text-secondary">{summary}</span>
        {item.isError && <span className="text-[10px] text-loss font-semibold shrink-0">error</span>}
        <span className="text-text-muted text-xs shrink-0">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 min-w-0">
          {isEdit && inp.old_string !== undefined && (
            <Code lang="diff" code={String(inp.old_string).split('\n').map((l: string) => '- ' + l).join('\n') + '\n' + String(inp.new_string).split('\n').map((l: string) => '+ ' + l).join('\n')} />
          )}
          {isWrite && <Code lang="" code={String(inp.content || '').slice(0, 6000)} />}
          {item.result && <Code lang="" code={item.result} muted />}
        </div>
      )}
    </div>
  )
}

// ── lightweight markdown (no deps) ─────────────────────────────────────
function Markdown({ text }: { text: string }) {
  const parts: { code: boolean; lang?: string; body: string }[] = []
  const re = /```(\w*)\n?([\s\S]*?)```/g
  let last = 0, m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push({ code: false, body: text.slice(last, m.index) })
    parts.push({ code: true, lang: m[1], body: m[2].replace(/\n$/, '') })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ code: false, body: text.slice(last) })
  return (
    <div className="space-y-2">
      {parts.map((p, i) => p.code ? <Code key={i} lang={p.lang || ''} code={p.body} /> : <Prose key={i} text={p.body} />)}
    </div>
  )
}

function Prose({ text }: { text: string }) {
  const lines = text.replace(/^\n+|\n+$/g, '').split('\n')
  return (
    <div className="space-y-1">
      {lines.map((ln, i) => {
        const h = ln.match(/^(#{1,3})\s+(.*)/)
        if (h) return <p key={i} className={`font-bold text-text-primary ${h[1].length === 1 ? 'text-base' : 'text-[15px]'}`}>{inline(h[2])}</p>
        const bullet = ln.match(/^\s*[-*]\s+(.*)/)
        if (bullet) return <div key={i} className="flex gap-2 pl-1"><span className="text-accent mt-1.5 w-1 h-1 rounded-full bg-accent shrink-0" /><span className="min-w-0">{inline(bullet[1])}</span></div>
        const num = ln.match(/^\s*(\d+)\.\s+(.*)/)
        if (num) return <div key={i} className="flex gap-2 pl-1"><span className="text-accent font-semibold shrink-0">{num[1]}.</span><span className="min-w-0">{inline(num[2])}</span></div>
        if (!ln.trim()) return <div key={i} className="h-1" />
        return <p key={i} className="break-words">{inline(ln)}</p>
      })}
    </div>
  )
}

// inline **bold**, `code`
function inline(s: string): (string | JSX.Element)[] {
  const out: (string | JSX.Element)[] = []
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`)/g
  let last = 0, m: RegExpExecArray | null, k = 0
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    if (m[2]) out.push(<strong key={k++} className="font-semibold text-text-primary">{m[2]}</strong>)
    else if (m[3]) out.push(<code key={k++} className="font-mono text-[0.85em] bg-tint/[0.08] text-accent rounded px-1 py-0.5">{m[3]}</code>)
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

function Code({ lang, code, muted }: { lang: string; code: string; muted?: boolean }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) }) }
  return (
    <div className="relative group/code min-w-0 rounded-lg ring-1 ring-border bg-bg-base/70 overflow-hidden">
      {lang && <div className="px-3 py-1 text-[10px] font-mono text-text-muted border-b border-border">{lang}</div>}
      <button onClick={copy} className="absolute top-1 right-1 opacity-0 group-hover/code:opacity-100 text-[10px] px-1.5 py-0.5 rounded bg-bg-elevated ring-1 ring-border text-text-muted hover:text-text-primary z-10">
        {copied ? 'copied' : 'copy'}
      </button>
      <pre className="text-[12px] font-mono leading-relaxed overflow-x-auto p-3 max-h-80 whitespace-pre">
        {lang === 'diff'
          ? <code>{code.split('\n').map((l, i) => (
              <div key={i} className={l.startsWith('+') ? 'text-profit' : l.startsWith('-') ? 'text-loss' : 'text-text-secondary'}>{l || ' '}</div>
            ))}</code>
          : <code className={muted ? 'text-text-secondary' : 'text-text-primary'}>{code}</code>}
      </pre>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="text-center py-16">
      <div className="grid place-items-center w-14 h-14 rounded-2xl bg-gradient-to-br from-accent to-accent-dim shadow-glow-accent mx-auto mb-4">
        <Icon name="terminal" size={26} className="text-white" />
      </div>
      <p className="text-base font-semibold text-text-primary">Full Claude Code, on the VPS</p>
      <p className="text-sm text-text-muted mt-1 max-w-sm mx-auto">It reads and edits files, runs bash and git, and ships — autonomously, right in your repo.</p>
    </div>
  )
}

function GateMsg({ state }: { state: 'disabled' | 'forbidden' | 'nosdk' }) {
  return (
    <div className="max-w-lg mx-auto mt-16">
      <div className="glass p-6 text-sm text-text-secondary space-y-2">
        <h2 className="text-lg font-bold text-text-primary">Claude Console</h2>
        {state === 'disabled' && <p>Console is <b className="text-text-primary">disabled</b>. Set <code className="text-accent">CONSOLE_PASSWORD</code> in the VPS <code>.env</code> and restart the dashboard.</p>}
        {state === 'forbidden' && <p>Your IP is <b className="text-loss">not allowed</b>. Add it to <code className="text-accent">CONSOLE_ALLOWED_IPS</code> on the VPS.</p>}
        {state === 'nosdk' && <p><code className="text-accent">claude-agent-sdk</code> is not installed on the server.</p>}
      </div>
    </div>
  )
}

function ConsoleLogin({ onAuthed }: { onAuthed: () => void }) {
  const [pw, setPw] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await consoleFetch('/api/console/login', { method: 'POST', body: JSON.stringify({ password: pw }) })
      if (r.status === 403) { setErr('Your IP is not allowed.'); return }
      if (!r.ok) { setErr('Wrong password.'); return }
      const d = await r.json(); setConsoleToken(d.token); onAuthed()
    } catch { setErr('Connection failed.') } finally { setBusy(false) }
  }
  return (
    <div className="max-w-sm mx-auto mt-20">
      <form onSubmit={submit} className="glass p-6 space-y-4">
        <div className="grid place-items-center w-12 h-12 rounded-2xl bg-gradient-to-br from-accent to-accent-dim shadow-glow-accent mx-auto">
          <Icon name="terminal" size={22} className="text-white" />
        </div>
        <div className="text-center">
          <h2 className="text-xl font-bold text-text-primary">Unlock Console</h2>
          <p className="text-xs text-text-muted mt-1">Separate password from the dashboard. Grants full Claude Code on the VPS.</p>
        </div>
        <input type="password" autoFocus value={pw} onChange={e => setPw(e.target.value)} placeholder="Console password"
               className="w-full bg-bg-elevated rounded-xl px-3 py-2.5 text-sm text-text-primary placeholder:text-text-muted outline-none ring-1 ring-border focus:ring-accent/60" />
        {err && <p className="text-xs text-loss text-center">{err}</p>}
        <button type="submit" disabled={busy || !pw} className="w-full h-10 rounded-xl bg-accent text-white text-sm font-semibold hover:bg-accent-dim disabled:opacity-50">
          {busy ? 'Unlocking…' : 'Unlock'}
        </button>
      </form>
    </div>
  )
}
