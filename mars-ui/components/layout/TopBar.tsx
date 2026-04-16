'use client'

import { Sun, Moon } from 'lucide-react'
import { useTheme } from '@/contexts/ThemeContext'

export default function TopBar() {
  const { theme, toggleTheme } = useTheme()

  return (
    <header
      className="flex flex-col flex-shrink-0 border-b"
      style={{
        backgroundColor: 'var(--mars-color-surface-raised)',
        borderColor: 'var(--mars-color-border)',
      }}
      role="banner"
    >
      <div
        className="flex items-center justify-center px-4 relative"
        style={{ height: '44px' }}
      >
        {/* Centered title */}
        <h1
          className="text-base font-bold tracking-wide"
          style={{ color: 'var(--mars-color-text)', fontFamily: 'var(--mars-font-sans)' }}
        >
          AI WEEKLY
        </h1>

        {/* Right: theme toggle only */}
        <div className="absolute right-4 flex items-center">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-mars-md transition-colors duration-mars-fast
              hover:bg-[var(--mars-color-bg-hover)]"
            style={{ color: 'var(--mars-color-text-secondary)' }}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            title={`${theme === 'dark' ? 'Light' : 'Dark'} mode`}
          >
            {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          </button>
        </div>
      </div>
    </header>
  )
}
