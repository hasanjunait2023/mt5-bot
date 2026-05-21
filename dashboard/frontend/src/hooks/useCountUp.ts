import { useEffect, useRef, useState } from 'react'

const prefersReduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Animates a number from 0 to `value` once on first mount (the premium
 * "reveal"). Subsequent value changes render instantly — continuous
 * re-animation on live ticks is distracting on a trading terminal.
 */
export function useCountUp(value: number, duration = 900): number {
  const [display, setDisplay] = useState(prefersReduced() ? value : 0)
  const done = useRef(false)

  useEffect(() => {
    if (done.current) {
      setDisplay(value)
      return
    }
    done.current = true
    if (prefersReduced() || !Number.isFinite(value)) {
      setDisplay(value)
      return
    }
    let raf = 0
    const start = performance.now()
    const from = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
      setDisplay(from + (value - from) * eased)
      if (t < 1) raf = requestAnimationFrame(tick)
      else setDisplay(value)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return display
}

/**
 * Returns 'up' | 'down' | null for ~700ms whenever `value` moves.
 * Drives the green/red background flash on live numeric updates —
 * a classic terminal cue that mitigates change blindness.
 */
export function useValueFlash(value: number): 'up' | 'down' | null {
  const prev = useRef(value)
  const [dir, setDir] = useState<'up' | 'down' | null>(null)

  useEffect(() => {
    if (value === prev.current) return
    const next = value > prev.current ? 'up' : 'down'
    prev.current = value
    setDir(next)
    const id = setTimeout(() => setDir(null), 700)
    return () => clearTimeout(id)
  }, [value])

  return dir
}
