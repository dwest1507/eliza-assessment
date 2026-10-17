import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import AmbientBackground from '@/components/AmbientBackground'
import './globals.css'

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'SEC Filings Research',
  description:
    'Ask business questions about public Companies and get answers cited to their 10-K and 10-Q Filings.',
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <AmbientBackground />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  )
}
