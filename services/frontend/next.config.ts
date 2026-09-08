import type { NextConfig } from 'next'

// Docker/local: relative /api is rewritten to FastAPI.
// Render: NEXT_PUBLIC_API_URL is the public API origin, so no rewrite
// (uploads and /speak audio go straight to the API origin).
const publicApi = process.env.NEXT_PUBLIC_API_URL ?? ''
const useApiRewrites = !publicApi.startsWith('http')
const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000'

const nextConfig: NextConfig = {
  ...(process.env.VERCEL ? {} : { output: 'standalone' as const }),
  async rewrites() {
    if (!useApiRewrites) {
      return []
    }
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ]
  },
}

export default nextConfig
