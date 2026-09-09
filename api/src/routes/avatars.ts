import { Hono } from 'hono'

import type { Context } from '../context'

const app = new Hono<Context>()

/**
 * Static 3D avatar models stored in R2 (Workers static assets cap individual
 * files at 25 MiB, which mpfb.glb exceeds).
 */
app.get('/:name', async (c) => {
  const name = c.req.param('name')
  if (!/^[a-zA-Z0-9._-]+$/.test(name) || !c.env.UPLOADS) {
    return c.json({ detail: 'Not Found' }, 404)
  }

  const object = await c.env.UPLOADS.get(`avatars/${name}`)
  if (!object) {
    return c.json({ detail: 'Not Found' }, 404)
  }

  const headers = new Headers()
  object.writeHttpMetadata(headers)
  headers.set('Cache-Control', 'public, max-age=86400')
  headers.set('ETag', object.httpEtag)
  headers.set('Content-Length', String(object.size))
  return new Response(object.body, { headers })
})

export default app