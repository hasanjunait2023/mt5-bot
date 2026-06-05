import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/api'

interface NextBrief {
  session: string
  fires_at_utc: string
  fires_at_bd: string
  fires_bd_hhmm?: string
  minutes_until: number
}

interface TimePayload {
  utc_hhmm: string
  bd_hhmm:  string
  session:  string
  session_label: string
  overlap?: boolean
  next_brief: NextBrief | null
}

const SESSION_STYLES: Record<string, string> = {
  london: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  ny:     'bg-sky-500/15    text-sky-300    ring-sky-500/30',
  asia:   'bg-violet-500/15 text-violet-300 ring-violet-500/30',
  off:    'bg-tint/[0.05] text-text-secondary ring-border',
}

function fmtCountdown(mins: number): string {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return `${h}h ${m}m`
}

export function SessionClock() {
  const [data, setData] = useState<TimePayload | null>(null)
  const [tick, setTick] = useState(0)        // forces re-render every second

  // Fetch from API every 30s (cheap), tick locally every second for the live clocks
  useEffect(() => {
    let dead = false
    const fetchTime = async () => {
      try {
        const r = await apiFetch('/system/time')
        if (!r.ok) return
        const d: TimePayload = await r.json()
        if (!dead) setData(d)
      } catch {}
    }
    fetchTime()
    const fetchId = setInterval(fetchTime, 30_000)
    const tickId  = setInterval(() => setTick(t => (t + 1) % 60), 1_000)
    return () => { dead = true; clearInterval(fetchId); clearInterval(tickId) }
  }, [])

  if (!data) {
    return <div className="text-text-tertiary text-[11px] font-mono">⏳ syncing…</div>
  }

  // Re-derive HH:MM:SS locally so the seconds tick smoothly
  const now = new Date()
  const utcStr = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}`
  const bd     = new Date(now.getTime() + 6 * 3600 * 1000)
  const bdStr  = `${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())}`
  const sessionStyle = SESSION_STYLES[data.session] ?? SESSION_STYLES.off

  return (
    <div className="hidden md:flex items-center gap-3 text-[11px]">
      <div className="flex items-baseline gap-2">
        <span className="text-text-tertiary uppercase tracking-wider text-[9px]">UTC</span>
        <span className="font-mono font-semibold tabular-nums text-text-primary">{utcStr}</span>
        <span className="text-text-tertiary">·</span>
        <span className="text-text-tertiary uppercase tracking-wider text-[9px]">BD</span>
        <span className="font-mono font-semibold tabular-nums text-text-primary">{bdStr}</span>
      </div>

      <span className={`px-2 py-0.5 rounded-md ring-1 text-[10px] font-semibold tracking-wide ${sessionStyle}`}>
        {data.session_label}
      </span>

      {data.overlap && (
        <span className="px-2 py-0.5 rounded-md ring-1 ring-emerald-500/40 bg-emerald-500/15
                         text-emerald-300 text-[10px] font-semibold tracking-wide animate-pulse2">
          🔥 PEAK
        </span>
      )}

      {data.next_brief && (
        <div className="hidden lg:flex items-center gap-1.5 text-text-tertiary font-mono">
          <span className="text-[10px] uppercase tracking-wider">Next brief</span>
          <span className="text-text-secondary font-semibold">
            {capitalize(data.next_brief.session)}
            {data.next_brief.fires_bd_hhmm && ` ${data.next_brief.fires_bd_hhmm} BD`}
            {' · '}{fmtCountdown(data.next_brief.minutes_until)}
          </span>
        </div>
      )}
    </div>
  )
  void tick    // referenced to keep eslint quiet; tick triggers re-render
}

function pad(n: number): string { return String(n).padStart(2, '0') }
function capitalize(s: string): string { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }
