/**
 * Single source of truth for recharts styling. Values are read from the live
 * theme CSS vars (index.css) via getters, so charts follow the light/dark
 * toggle on the next render (the whole tree re-renders when the theme flips).
 */
function v(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw ? `rgb(${raw})` : fallback
}
function va(name: string, alpha: number, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw ? `rgb(${raw} / ${alpha})` : fallback
}

export const CHART = {
  get profit() { return v('--profit', '#16a34a') },
  get loss() { return v('--loss', '#e14348') },
  get accent() { return v('--accent', '#f1592b') },
  get axis() { return v('--text-muted', '#969da8') },        // minor tick labels
  get axisStrong() { return v('--text-secondary', '#646b78') }, // primary axis labels
  get grid() { return va('--line', 0.12, 'rgba(120,130,150,0.14)') },
}

/** Spread onto <Tooltip /> — getters re-evaluate per render so it tracks theme. */
export const tooltipProps = {
  get cursor() { return { stroke: va('--line', 0.18, 'rgba(120,130,150,0.2)'), strokeWidth: 1 } },
  get contentStyle() {
    return {
      background: v('--bg-surface', '#ffffff'),
      border: `1px solid ${va('--line', 0.12, 'rgba(0,0,0,0.1)')}`,
      borderRadius: 12,
      boxShadow: '0 14px 36px -16px rgba(17,20,28,0.35)',
      padding: '8px 10px',
    }
  },
  get labelStyle() { return { color: v('--text-muted', '#969da8'), fontSize: 11, marginBottom: 2 } },
  get itemStyle() {
    return { color: v('--text-primary', '#17191e'), fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }
  },
}

/** Shared empty-state shell so "no data" reads like the rest of the UI. */
export const emptyClass =
  'flex items-center justify-center text-text-muted text-sm rounded-xl ' +
  'bg-tint/[0.04] ring-1 ring-line/[0.08]'
