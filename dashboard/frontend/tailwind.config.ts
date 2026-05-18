import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base:     '#0a0b0e',
          surface:  '#111318',
          elevated: '#181c24',
          overlay:  '#1e2330',
        },
        border: { DEFAULT: '#252b3b', focus: '#3b82f6' },
        text: {
          primary:   '#e8ecf4',
          secondary: '#8896a8',
          muted:     '#4a5568',
        },
        profit:  '#10b981',
        loss:    '#ef4444',
        warning: '#f59e0b',
        accent:  '#3b82f6',
        'accent-dim': '#1d4ed8',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
        sans: ['Inter', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      animation: {
        pulse2: 'pulse2 2s ease-in-out infinite',
      },
      keyframes: {
        pulse2: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.3' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
