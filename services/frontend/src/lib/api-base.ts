/** Backend origin used by browser fetches. No trailing slash. */
const configuredApi = process.env.NEXT_PUBLIC_API_URL
const renderApi =
  typeof window !== 'undefined' &&
  window.location.hostname === 'virtual-professor-frontend.onrender.com'
    ? 'https://virtual-professor-api.onrender.com'
    : undefined

export const API_BASE = (configuredApi ?? renderApi ?? '/api').replace(/\/$/, '')
