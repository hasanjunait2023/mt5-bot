import { useState } from 'react'
import clsx from 'clsx'

// Premium 3D circular avatar for a trading agent. Renders /agents/<avatar>.jpg when
// present (drop a real photo there); otherwise a deterministic gradient + initials.
// Glossy top-light + gradient ring + drop shadow give the 3D feel; an in-trade tone
// lights the ring with the matching glow.

type Tone = 'profit' | 'loss' | 'accent'

const TONE_RING: Record<Tone, string> = {
  profit: 'from-profit/70 via-profit/30 to-profit/5',
  loss: 'from-loss/70 via-loss/30 to-loss/5',
  accent: 'from-accent/70 via-accent/30 to-accent/5',
}
const TONE_GLOW: Record<Tone, string> = {
  profit: 'shadow-glow-profit', loss: 'shadow-glow-loss', accent: 'shadow-glow-accent',
}

// distinct gradient per personality for the fallback
const PALETTE: [string, string][] = [
  ['#6366f1', '#8b5cf6'], ['#0ea5e9', '#22d3ee'], ['#f59e0b', '#f97316'],
  ['#10b981', '#34d399'], ['#ec4899', '#f472b6'], ['#ef4444', '#fb7185'], ['#14b8a6', '#2dd4bf'],
]
function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}
function initials(name: string): string {
  return name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase()
}

export function AgentAvatar({ name, avatar, size = 52, tone }:
  { name: string; avatar?: string | null; size?: number; tone?: Tone }) {
  const [errored, setErrored] = useState(false)
  const [a, b] = PALETTE[hash(name) % PALETTE.length]
  const ring = tone ? TONE_RING[tone] : 'from-sheen/30 via-sheen/10 to-sheen/[0.03]'
  const showImg = avatar && !errored
  return (
    <div
      className={clsx('relative shrink-0 rounded-full', tone && TONE_GLOW[tone])}
      style={{ width: size, height: size }}
    >
      {/* gradient ring */}
      <div className={clsx('absolute inset-0 rounded-full bg-gradient-to-br p-[2px]', ring)}>
        <div className="relative w-full h-full rounded-full overflow-hidden bg-bg-surface ring-1 ring-black/30">
          {showImg ? (
            <img
              src={`/agents/${avatar}.jpg`}
              alt={name}
              loading="lazy"
              onError={() => setErrored(true)}
              className="w-full h-full object-cover"
            />
          ) : (
            <div
              className="w-full h-full flex items-center justify-center font-bold text-white tracking-tight"
              style={{
                background: `radial-gradient(circle at 32% 26%, ${a}, ${b} 78%)`,
                fontSize: size * 0.36,
              }}
            >
              {initials(name)}
            </div>
          )}
          {/* glossy 3D highlight */}
          <div
            className="pointer-events-none absolute inset-0 rounded-full"
            style={{ background: 'linear-gradient(150deg, rgba(255,255,255,0.30), rgba(255,255,255,0) 46%)' }}
          />
          {/* bottom inner shade for depth */}
          <div
            className="pointer-events-none absolute inset-0 rounded-full"
            style={{ boxShadow: 'inset 0 -6px 12px -6px rgba(0,0,0,0.55)' }}
          />
        </div>
      </div>
    </div>
  )
}
