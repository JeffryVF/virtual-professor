import type { NextConfig } from 'next'

// API calls are handled by nginx (port 80): location /api/ → backend:8000
// When on port 3000 (local dev), these rewrites provide the same routing.
// BACKEND_INTERNAL_URL is set in docker-compose.yml.
const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000'

const nextConfig: NextConfig = {
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ]
  },
}

export default nextConfig
