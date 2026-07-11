import type { Metadata } from 'next'
import './globals.css'
import { Toaster } from '@/components/ui/sonner'
import AuthProviderWrapper from '@/components/auth/AuthProviderWrapper'

export const metadata: Metadata = {
  title: 'Virtual Professor',
  description: 'AI-powered virtual professors',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProviderWrapper>
          {children}
          <Toaster richColors />
        </AuthProviderWrapper>
      </body>
    </html>
  )
}
