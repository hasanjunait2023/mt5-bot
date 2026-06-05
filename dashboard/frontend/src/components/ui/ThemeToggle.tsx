import { useTheme } from '../../contexts/ThemeContext'

/** Sun/moon theme switch — segmented pill, matches the topbar status chips. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggle}
      title={isDark ? 'Switch to light' : 'Switch to dark'}
      aria-label="Toggle colour theme"
      className="relative grid place-items-center w-8 h-8 rounded-full
                 bg-tint/[0.05] ring-1 ring-border text-text-secondary
                 hover:text-text-primary hover:bg-tint/[0.09] transition-colors"
    >
      <span className="relative w-[18px] h-[18px]">
        {/* Sun */}
        <svg
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
          className={`absolute inset-0 transition-all duration-300 ${
            isDark ? 'opacity-0 -rotate-90 scale-50' : 'opacity-100 rotate-0 scale-100 text-accent'
          }`}
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
        {/* Moon */}
        <svg
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
          className={`absolute inset-0 transition-all duration-300 ${
            isDark ? 'opacity-100 rotate-0 scale-100 text-accent' : 'opacity-0 rotate-90 scale-50'
          }`}
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      </span>
    </button>
  )
}
