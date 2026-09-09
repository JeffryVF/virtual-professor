import type { Env } from './types'

export type Context = {
  Bindings: Env
  Variables: Record<string, never>
}