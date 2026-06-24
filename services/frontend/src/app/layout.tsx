import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Toaster } from '@/components/ui/sonner'
import AuthProviderWrapper from '@/components/auth/AuthProviderWrapper'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Virtual Professor',
  description: 'AI-powered virtual professors',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <AuthProviderWrapper>
          {children}
          <Toaster richColors />
        </AuthProviderWrapper>
      </body>
    </html>
  )
}
