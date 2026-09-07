/** Backend origin used by browser fetches. No trailing slash.

In Docker/nginx local: `/api` (rewritten to the FastAPI service).
On Vercel: the public Render URL, e.g. `https://virtual-professor-api.onrender.com`.
*/
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? '/api').replace(/\/$/, '')
