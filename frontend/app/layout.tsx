import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SEC Filings Research',
  description:
    'Ask business questions about public Companies and get answers cited to their 10-K and 10-Q Filings.',
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
