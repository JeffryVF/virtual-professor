/** Backend origin used by browser fetches. No trailing slash.
 * Set NEXT_PUBLIC_API_URL at build time to the deployed Worker URL
 * (e.g. https://virtual-professor-api.<subdomain>.workers.dev).
 * Falls back to /api (local dev rewrite / nginx). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? '/api').replace(/\/$/, '')