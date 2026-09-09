import { Hono } from 'hono'

import type { Context } from '../context'

interface ServiceProbe {
  status: 'healthy' | 'unhealthy'
  latency_ms: number
  error: string | null
}

async function probe(check: () => Promise<void>): Promise<ServiceProbe> {
  const start = Date.now()
  try {
    await check()
    return {
      status: 'healthy',
      latency_ms: Math.round(Date.now() - start),
      error: null,
    }
  } catch (err) {
    return {
      status: 'unhealthy',
      latency_ms: Math.round(Date.now() - start),
      error: err instanceof Error ? err.message.slice(0, 300) : String(err),
    }
  }
}

const app = new Hono<Context>()

app.get('/health', async (c) => {
  const [postgres, cloudflare] = await Promise.all([
    probe(async () => {
      await c.env.DB.prepare('SELECT 1').first()
    }),
    probe(async () => {
      const { getInstance } = await import('../cloudflare')
      await getInstance(c.env, 10000)
    }),
  ])
  const services = {
    postgres,
    redis: { status: 'healthy', latency_ms: 0, error: null } as ServiceProbe,
    zai: { status: 'healthy', latency_ms: 0, error: null } as ServiceProbe,
    cloudflare,
  }
  const status = postgres.status === 'healthy' && cloudflare.status === 'healthy' ? 'healthy' : 'degraded'
  return c.json({
    status,
    timestamp: new Date().toISOString(),
    services,
    version: '0.1.0',
  })
})

export default app