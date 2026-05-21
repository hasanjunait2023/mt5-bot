import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Cinematic near-black with a faint cool undertone (not flat gray)
        bg: {
          base:     '#070809',
          surface:  '#0e1014',
          elevated: '#15181f',
          overlay:  '#1c212b',
        },
        // Glass strokes — subtle light alpha reads as "premium edge"
        border: {
          DEFAULT: 'rgba(255,255,255,0.07)',
          strong:  'rgba(255,255,255,0.12)',
          focus:   '#3b82f6',
        },
        text: {
          primary:   '#eef1f7',
          secondary: '#9aa6b8',
          muted:     '#5a6577',
        },
        profit:  '#22c55e',
        loss:    '#f43f5e',
        warning: '#f59e0b',
        accent:  '#3b82f6',
        'accent-dim': '#1d4ed8',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
        sans: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
      },
      boxShadow: {
        card:        '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.7)',
        'card-hover':'0 1px 0 0 rgba(255,255,255,0.07) inset, 0 16px 40px -16px rgba(0,0,0,0.85)',
        'glow-accent': '0 0 0 1px rgba(59,130,246,0.35), 0 8px 30px -8px rgba(59,130,246,0.45)',
        'glow-profit': '0 0 18px -4px rgba(34,197,94,0.55)',
        'glow-loss':   '0 0 18px -4px rgba(244,63,94,0.55)',
        topbar:      '0 1px 0 0 rgba(255,255,255,0.05), 0 6px 24px -12px rgba(0,0,0,0.8)',
      },
      backgroundImage: {
        'glass': 'linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012))',
        'glass-hover': 'linear-gradient(180deg, rgba(255,255,255,0.075), rgba(255,255,255,0.02))',
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
