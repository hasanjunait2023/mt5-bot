---
name: MT5 Dashboard
description: Dark trading terminal design system for the MT5 real-time monitoring panel.
version: alpha

colors:
  bg-base:        "#0a0b0e"
  bg-surface:     "#111318"
  bg-elevated:    "#181c24"
  bg-overlay:     "#1e2330"
  border:         "#252b3b"
  border-focus:   "#3b82f6"
  text-primary:   "#e8ecf4"
  text-secondary: "#8896a8"
  text-muted:     "#4a5568"
  accent:         "#3b82f6"
  accent-dim:     "#1d4ed8"
  profit:         "#10b981"
  loss:           "#ef4444"
  warning:        "#f59e0b"
  chart-1:        "#3b82f6"
  chart-2:        "#10b981"
  chart-3:        "#f59e0b"
  chart-4:        "#8b5cf6"
  chart-5:        "#ef4444"

typography:
  price:
    fontFamily: "JetBrains Mono, Fira Code, Consolas, monospace"
    fontSize: 1rem
    fontFeature: "tnum"
  heading:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: 1.125rem
    fontWeight: 600
  body-sm:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: 0.875rem
  label-caps:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 0.75rem
    letterSpacing: 0.05em

rounded:
  sm: 4px
  md: 8px
  lg: 12px

spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px

components:
  metric-card:
    backgroundColor: "{colors.bg-surface}"
    rounded: "{rounded.md}"
    padding: 20px 24px
  metric-value:
    typography: "{typography.price}"
    textColor: "{colors.text-primary}"
  metric-label:
    typography: "{typography.label-caps}"
    textColor: "{colors.text-secondary}"
  table-header:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.label-caps}"
    padding: 8px 12px
  table-row:
    backgroundColor: "transparent"
    textColor: "{colors.text-primary}"
    padding: 10px 12px
  table-row-hover:
    backgroundColor: "{colors.bg-elevated}"
  status-dot-running:
    backgroundColor: "{colors.profit}"
    size: 8px
  status-dot-stopped:
    backgroundColor: "{colors.loss}"
    size: 8px
  status-dot-warning:
    backgroundColor: "{colors.warning}"
    size: 8px
  badge-buy:
    backgroundColor: "{colors.bg-overlay}"
    textColor: "{colors.profit}"
    rounded: "{rounded.sm}"
    padding: 2px 8px
  badge-sell:
    backgroundColor: "{colors.bg-overlay}"
    textColor: "{colors.loss}"
    rounded: "{rounded.sm}"
    padding: 2px 8px
  sidebar:
    backgroundColor: "{colors.bg-surface}"
    width: 220px
  mobile-nav:
    backgroundColor: "{colors.bg-surface}"
    height: 64px
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: 8px 16px
  button-primary-hover:
    backgroundColor: "{colors.accent-dim}"
---

## Overview

Dark trading terminal — information-dense, zero-distraction. Inspired by Bloomberg
Terminal and TradingView. The color vocabulary is strictly limited: green=profit/BUY,
red=loss/SELL, blue=interactive. The only animation is the status dot pulse for the
live trader heartbeat.

All numeric values (prices, P&L, lot sizes, percentages) use JetBrains Mono with
`font-variant-numeric: tabular-nums` so digits align perfectly in tables.

## Colors

- **bg-base (#0a0b0e):** Page background — near-black, softer than pure black.
- **bg-surface (#111318):** Card and panel backgrounds. All MetricCards, sidebar, TopBar.
- **bg-elevated (#181c24):** Table header backgrounds, row hover states, inputs.
- **bg-overlay (#1e2330):** Tooltips, modals, dropdown menus.
- **profit (#10b981):** Positive P&L, BUY badges, winning trades, running status dot.
- **loss (#ef4444):** Negative P&L, SELL badges, losing trades, ERROR lines, stopped dot.
- **warning (#f59e0b):** Drawdown alerts, WARNING log lines, high-DD indicators.
- **accent (#3b82f6):** Active nav, focus rings, primary buttons, links.

## Typography

Two font families only:
1. **JetBrains Mono** — all prices, P&L, lot sizes, percentages, log timestamps.
   Always with `font-variant-numeric: tabular-nums`.
2. **Inter** — labels, headings, navigation, prose text.

## Layout

- **Sidebar** (≥768px): 220px fixed left, bg-surface, right border.
  Active nav: 2px left accent border + bg-elevated background.
- **Mobile bottom nav** (<768px): fixed 64px bottom bar, bg-surface, top border.
- **Content area**: 16px padding mobile → 24px desktop.
- **MetricCards grid**: 4-col desktop → 2-col tablet → 1-col mobile.

## Elevation & Depth

No shadows — depth via background color steps:
`bg-base` → `bg-surface` → `bg-elevated` → `bg-overlay`

## Shapes

Cards/panels: 8px. Badges/pills: 4px. Buttons: 4px. Charts: no radius.

## Components

### MetricCard
Large value (price font, 24px bold) + label-caps above. Optional delta row: ▲/▼
colored profit/loss. Optional sparkline 60px wide on the right.

### Table
Header: bg-elevated, label-caps. Rows: transparent, 1px border-bottom. Row hover:
bg-elevated, 100ms transition. Numbers: mono, right-aligned. Symbols: left-aligned badge.

### StatusDot
8px circle. Running: profit, CSS pulse (opacity 1→0.3→1, 2s infinite).
Stopped: loss, static. Warning: warning, static.

### LogLine
INFO: text-primary. WARNING: warning color. ERROR: loss color.
Lines with "BUY" or ">>": 2px profit left border. Lines with "SELL"/"FAIL": 2px loss border.

### PriceBar
4px track, 2px radius. Distance-to-SL (loss fill) vs distance-to-TP (profit fill).
Track background: bg-overlay.

## Do's and Don'ts

- **Do** use mono font for every number the user compares vertically.
- **Do** use profit/loss colors exclusively for financial direction.
- **Don't** use white backgrounds, shadows, or gradients on panels.
- **Don't** animate anything except the running status dot.
- **Don't** exceed 2 font families.
- **Don't** use border-radius larger than 8px on cards.
