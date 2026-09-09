import { defineWorkersConfig } from '@cloudflare/vitest-pool-workers/config'

export default defineWorkersConfig({
  test: {
    testTimeout: 30000,
    fileParallelism: false,
    poolOptions: {
      workers: {
        wrangler: { configPath: './test/wrangler.test.toml' },
      },
    },
  },
})