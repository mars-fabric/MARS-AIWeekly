'use client'

import { ReactNode } from 'react'
import TopBar from './TopBar'
import FooterBar from './FooterBar'

interface AppShellProps {
  children: ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  return (
    <div className="h-screen flex flex-col overflow-hidden" style={{ backgroundColor: 'var(--mars-color-bg)' }}>
      {/* Skip-to-content link (a11y) */}
      <a href="#mars-main-content" className="mars-skip-link">
        Skip to main content
      </a>

      <TopBar />

      {/* Body: Content only */}
      <div className="flex-1 flex min-h-0">
        <main
          id="mars-main-content"
          role="main"
          className="flex-1 min-h-0 overflow-auto"
          style={{ backgroundColor: 'var(--mars-color-bg)' }}
        >
          {children}
        </main>
      </div>

      <FooterBar />

      {/* Live region for screen reader announcements */}
      <div aria-live="polite" aria-atomic="true" className="mars-live-region" id="mars-live-announcements" />
    </div>
  )
}
