import { existsSync, readFileSync } from 'node:fs'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const apiDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const envPath = path.resolve(apiDir, '..', '.env')

function readEnv(file) {
  const values = {}
  if (!existsSync(file)) return values
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$/)
    if (!match) continue
    values[match[1]] = match[2].trim().replace(/^("|')|("|')$/g, '')
  }
  return values
}

const values = readEnv(envPath)
const deployVars = ['GEMINI_LLM_MODEL', 'GEMINI_FALLBACK_LLM_MODEL', 'TTS_MODEL_ES', 'TTS_MODEL_EN']
const resolved = Object.fromEntries(
  deployVars.map((name) => [name, process.env[name] || values[name]]),
)

if (!resolved.GEMINI_LLM_MODEL) {
  throw new Error('GEMINI_LLM_MODEL is required in the repo-root .env or environment.')
}

const args = ['wrangler', 'deploy']
for (const name of deployVars) {
  if (resolved[name]) args.push('--var', `${name}:${resolved[name]}`)
}

const wranglerCli = path.resolve(apiDir, 'node_modules', 'wrangler', 'bin', 'wrangler.js')
if (!existsSync(wranglerCli)) {
  throw new Error('Local Wrangler is missing. Run npm install in api/.')
}

const child = spawn(process.execPath, [wranglerCli, ...args.slice(1)], {
  cwd: apiDir,
  stdio: 'inherit',
})
child.on('error', (error) => {
  throw error
})
child.on('close', (code) => process.exit(code ?? 1))
