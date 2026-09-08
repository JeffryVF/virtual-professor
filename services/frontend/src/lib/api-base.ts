/** Backend origin used by browser fetches. No trailing slash.

In Docker/nginx local: `/api` (rewritten to the FastAPI service).
On Render (production): the public API URL, e.g. `https://virtual-professor-api.onrender.com`.
Adapted by `services/frontend/Dockerfile.prod` as a build arg (`NEXT_PUBLIC_API_URL`).
*/
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? '/api').replace(/\/$/, '')
