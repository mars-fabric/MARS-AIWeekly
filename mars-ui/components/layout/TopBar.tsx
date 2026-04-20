'use client'

import { Sun, Moon, Plus } from 'lucide-react'
import { useTheme } from '@/contexts/ThemeContext'

export default function TopBar() {
  const { theme, toggleTheme } = useTheme()

  return (
    <header
      className="flex flex-shrink-0 border-b"
      style={{
        backgroundColor: 'var(--mars-color-surface-raised)',
        borderColor: 'var(--mars-color-border)',
      }}
      role="banner"
    >
      <div
        className="flex items-center justify-between px-6 w-full"
        style={{ height: '64px' }}
      >
        {/* Left: App name + subtitle */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #6366f1, #3b82f6)' }}>
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-bold leading-tight"
              style={{ color: 'var(--mars-color-text)' }}>
              MARS - AI Weekly
            </h1>
            <p className="text-[11px] leading-tight"
              style={{ color: 'var(--mars-color-text-tertiary)' }}>
              AI-Powered Weekly Report Generator
            </p>
          </div>
        </div>

        {/* Right: theme toggle + New Session */}
        <div className="flex items-center gap-2">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md transition-colors duration-150
              hover:bg-[var(--mars-color-bg-hover)]"
            style={{ color: 'var(--mars-color-text-secondary)' }}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            title={`${theme === 'dark' ? 'Light' : 'Dark'} mode`}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('mars:new-session'))}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors"
            style={{
              backgroundColor: 'var(--mars-color-primary)',
              color: '#fff',
            }}
          >
            <Plus className="w-3.5 h-3.5" />
            New Session
          </button>
        </div>
      </div>
    </header>
  )
}
