import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Theme-driven tokens — values live as rgb-channel CSS vars in index.css
        // (:root = light "Finexy", .dark = dark). rgb(var(--x) / <alpha-value>)
        // keeps every Tailwind opacity modifier (bg-accent/10, text-muted/70…) working.
        bg: {
          base:     'rgb(var(--bg-base) / <alpha-value>)',
          surface:  'rgb(var(--bg-surface) / <alpha-value>)',
          elevated: 'rgb(var(--bg-elevated) / <alpha-value>)',
          overlay:  'rgb(var(--bg-overlay) / <alpha-value>)',
          ink:      'rgb(var(--bg-ink) / <alpha-value>)',
        },
        border: {
          DEFAULT: 'rgb(var(--line) / 0.12)',
          strong:  'rgb(var(--line) / 0.20)',
          focus:   'rgb(var(--accent) / <alpha-value>)',
        },
        text: {
          primary:   'rgb(var(--text-primary) / <alpha-value>)',
          secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          muted:     'rgb(var(--text-muted) / <alpha-value>)',
          onink:     'rgb(var(--text-onink) / <alpha-value>)',
        },
        // Surface tint (was bg-white/x), gradient sheen (was via-white/x), hairline
        tint:  'rgb(var(--tint) / <alpha-value>)',
        sheen: 'rgb(var(--sheen) / <alpha-value>)',
        line:  'rgb(var(--line) / <alpha-value>)',
        profit:  'rgb(var(--profit) / <alpha-value>)',
        loss:    'rgb(var(--loss) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        accent:  'rgb(var(--accent) / <alpha-value>)',
        'accent-dim': 'rgb(var(--accent-dim) / <alpha-value>)',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
        sans: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        card:        'var(--shadow-card)',
        'card-hover':'var(--shadow-card-hover)',
        'glow-accent': '0 0 0 1px rgb(var(--accent) / 0.30), 0 8px 30px -8px rgb(var(--accent) / 0.40)',
        'glow-profit': '0 0 18px -4px rgb(var(--profit) / 0.45)',
        'glow-loss':   '0 0 18px -4px rgb(var(--loss) / 0.45)',
        topbar:      'var(--shadow-topbar)',
      },
      backgroundImage: {
        'glass': 'linear-gradient(180deg, rgb(var(--sheen) / 0.05), rgb(var(--sheen) / 0.012))',
        'glass-hover': 'linear-gradient(180deg, rgb(var(--sheen) / 0.075), rgb(var(--sheen) / 0.02))',
      },
      animation: {
        pulse2:    'pulse2 2s ease-in-out infinite',
        rise:      'rise 0.6s cubic-bezier(0.22,1,0.36,1) both',
        'drift-a': 'drift-a 26s ease-in-out infinite',
        'drift-b': 'drift-b 32s ease-in-out infinite',
        'glow-ring': 'glow-ring 2.4s ease-out infinite',
        'flash-up':   'flash-up 0.7s ease-out',
        'flash-down': 'flash-down 0.7s ease-out',
        shimmer:   'shimmer 1.6s linear infinite',
      },
      keyframes: {
        pulse2: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.3' },
        },
        rise: {
          '0%':   { opacity: '0', transform: 'translateY(14px) scale(0.985)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'drift-a': {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '50%':      { transform: 'translate3d(6%, 4%, 0) scale(1.12)' },
        },
        'drift-b': {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1.05)' },
          '50%':      { transform: 'translate3d(-7%, -5%, 0) scale(0.92)' },
        },
        'glow-ring': {
          '0%':   { transform: 'scale(1)', opacity: '0.55' },
          '70%':  { transform: 'scale(2.6)', opacity: '0' },
          '100%': { transform: 'scale(2.6)', opacity: '0' },
        },
        'flash-up': {
          '0%':   { backgroundColor: 'rgba(34,197,94,0.22)' },
          '100%': { backgroundColor: 'rgba(34,197,94,0)' },
        },
        'flash-down': {
          '0%':   { backgroundColor: 'rgba(244,63,94,0.22)' },
          '100%': { backgroundColor: 'rgba(244,63,94,0)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
