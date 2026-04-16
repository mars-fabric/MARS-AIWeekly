import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'
import AppShell from '@/components/layout/AppShell'

export const metadata: Metadata = {
  title: 'AI Weekly',
  description: 'AI Weekly Report Generator',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" data-theme="dark" data-scroll-behavior="smooth">
      <body className="font-sans">
        <Providers>
          <AppShell>
            {children}
          </AppShell>
        </Providers>
      </body>
    </html>
  )
}
