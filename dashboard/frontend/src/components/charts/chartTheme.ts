/**
 * Single source of truth for recharts styling — kept in sync with the
 * premium token palette in tailwind.config.ts / index.css.
 */
export const CHART = {
  profit: '#22c55e',
  loss:   '#f43f5e',
  accent: '#3b82f6',
  axis:       '#5a6577', // text.muted — minor tick labels
  axisStrong: '#9aa6b8', // text.secondary — primary axis labels
  grid:       'rgba(255,255,255,0.055)',
} as const

/** Spread onto <Tooltip /> for a glass tooltip that matches surfaces. */
export const tooltipProps = {
  cursor: { stroke: 'rgba(255,255,255,0.12)', strokeWidth: 1 },
  contentStyle: {
    background: 'rgba(20,24,31,0.92)',
    border: '1px solid rgba(255,255,255,0.10)',
    borderRadius: 10,
    boxShadow: '0 12px 32px -12px rgba(0,0,0,0.85)',
    backdropFilter: 'blur(8px)',
    padding: '8px 10px',
  } as const,
  labelStyle: { color: '#9aa6b8', fontSize: 11, marginBottom: 2 } as const,
  itemStyle: { color: '#eef1f7', fontFamily: 'JetBrains Mono, monospace', fontSize: 12 } as const,
}

/** Shared empty-state shell so "no data" reads like the rest of the UI. */
export const emptyClass =
  'flex items-center justify-center text-text-muted text-sm rounded-xl ' +
  'bg-white/[0.025] ring-1 ring-white/[0.06]'
