#!/usr/bin/env node
/**
 * Deploy the virtual-professor-api Cloudflare Worker.
 *
 *   node scripts/deploy-worker.mjs [--cors <https://frontend.pages.dev>]
 *
 * Reads credentials from the repo-root .env (CLOUDFLARE_API_TOKEN,
 * CLOUDFLARE_ACCOUNT_ID) or from the environment. If you prefer OAuth, run
 * `npx wrangler login` instead and leave CLOUDFLARE_API_TOKEN unset.
 *
 * Required token permissions: D1 Edit, Workers Scripts Edit,
 * Workers Routes Edit, R2 Edit, Account Settings Read.
 */
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const API_DIR = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(API_DIR, '..')
const ENV_PATH = path.resolve(REPO_ROOT, '.env')
const WRANGLER_TOML = path.resolve(API_DIR, 'wrangler.toml')

const D1_NAME = 'virtual-professor-db'
const R2_NAME = 'virtual-professor-uploads'
const SECRET_NAMES = [
  'CLOUDFLARE_ACCOUNT_ID',
  'CLOUDFLARE_API_TOKEN',
  'CLOUDFLARE_AI_SEARCH_INSTANCE',
  'ZAI_API_KEY',
  'JWT_SECRET_KEY',
  'ADMIN_API_KEY',
  'ADMIN_EMAIL',
  'ADMIN_PASSWORD',
]

function log(msg) {
  process.stdout.write(`[deploy] ${msg}\n`)
}

function die(msg) {
  process.stderr.write(`[deploy] ERROR: ${msg}\n`)
  process.exit(1)
}

function parseEnv(file) {
  const out = {}
  if (!existsSync(file)) return out
  for (const raw of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq === -1) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    out[key] = value
  }
  return out
}

const envFile = parseEnv(ENV_PATH)

function value(key) {
  return process.env[key] ?? envFile[key]
}

function run(cmd, args, { input, env = {} } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd: API_DIR,
      stdio: input !== undefined ? ['pipe', 'inherit', 'inherit'] : 'inherit',
      env: {
        ...process.env,
        CLOUDFLARE_API_TOKEN: process.env.CLOUDFLARE_API_TOKEN ?? envFile.CLOUDFLARE_API_TOKEN ?? '',
        CLOUDFLARE_ACCOUNT_ID: process.env.CLOUDFLARE_ACCOUNT_ID ?? envFile.CLOUDFLARE_ACCOUNT_ID ?? '',
        ...env,
      },
    })
    child.on('error', reject)
    if (input !== undefined) {
      child.on('spawn', () => child.stdin.end(input))
    }
    child.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited with code ${code}`))))
  })
}

function patchD1Id(tomlId) {
  const toml = readFileSync(WRANGLER_TOML, 'utf8')
  const next = toml.replace(
    /(database_name\s*=\s*"virtual-professor-db"\s*\n\s*database_id\s*=\s*")[^"]+(")/,
    `$1${tomlId}$2`,
  )
  if (next === toml) die('Could not patch database_id in wrangler.toml')
  writeFileSync(WRANGLER_TOML, next)
  log(`Patched wrangler.toml database_id -> ${tomlId}`)
}

function corsFlag() {
  const i = process.argv.indexOf('--cors')
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : null
}

async function ensureD1(token, accountId) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const listResponse = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database?per_page=50`,
    { headers },
  )
  if (!listResponse.ok) {
    die(
      `Could not read D1 databases (HTTP ${listResponse.status}). ` +
        `Is the token valid and does it have D1 Edit on account ${accountId}? ` +
        'Create a token in https://dash.cloudflare.com + /my-profile/api-tokens',
    )
  }
  const list = await listResponse.json()
  const existing = list.result?.find((db) => db.name === D1_NAME)
  if (existing) {
    log(`D1 ${D1_NAME} already exists (${existing.uuid})`)
    return existing.uuid
  }
  const create = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database`,
    { method: 'POST', headers, body: JSON.stringify({ name: D1_NAME }) },
  )
  if (!create.ok) {
    const body = await create.text()
    die(`Could not create D1 ${D1_NAME} (HTTP ${create.status}): ${body.slice(0, 300)}`)
  }
  const created = await create.json()
  log(`Created D1 ${D1_NAME} (${created.result?.uuid})`)
  return created.result.uuid
}

async function ensureR2(token, accountId, name) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const head = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets/${name}`,
    { method: 'HEAD', headers },
  )
  if (head.ok) {
    log(`R2 bucket ${name} already exists`)
    return
  }
  const create = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets`,
    { method: 'POST', headers, body: JSON.stringify({ name }) },
  )
  if (!create.ok) {
    const body = await create.text()
    const existing = await fetch(
      `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets/${name}`,
      { headers },
    )
    if (existing.ok) {
      log(`R2 bucket ${name} exists (race)`)
      return
    }
    die(`Could not create R2 bucket ${name} (HTTP ${create.status}): ${body.slice(0, 300)}`)
  }
  log(`Created R2 bucket ${name}`)
}

async function uploadAvatar(token, accountId) {
  const defaultPath = process.env.AVATAR_GLB_PATH ?? path.resolve(REPO_ROOT, 'services/frontend/avatars/mpfb.glb')
  const filePath = path.resolve(defaultPath)
  if (!existsSync(filePath)) {
    log(`Skipping avatar upload: ${filePath} not found (set AVATAR_GLB_PATH or restore the .glb)`)
    return
  }
  const stat = await import('node:fs').then((fs) => fs.promises.stat(filePath))
  const url = new URL(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets/${R2_NAME}/objects/avatars%2Fmpfb.glb`,
  )
  const res = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'model/gltf-binary',
      'Content-Length': String(stat.size),
    },
    body: readFileSync(filePath),
  })
  if (!res.ok) {
    die(`Avatar upload to R2 failed (HTTP ${res.status}): ${(await res.text()).slice(0, 300)}`)
  }
  log(`Uploaded avatar mpfb.glb (${(stat.size / 1024 / 1024).toFixed(1)} MB) -> R2 avatars/mpfb.glb`)
}

async function main() {
  const accountId = value('CLOUDFLARE_ACCOUNT_ID')
  const token = value('CLOUDFLARE_API_TOKEN')

  for (const key of ['CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_AI_SEARCH_INSTANCE', 'ZAI_API_KEY', 'JWT_SECRET_KEY', 'ADMIN_EMAIL']) {
    if (!value(key)) die(`Missing ${key} in .env or environment`)
  }
  if (!token) {
    log('No CLOUDFLARE_API_TOKEN set; falling back to wrangler OAuth (run `npx wrangler login` first).')
  }

  const insecure = process.argv.includes('--allow-insecure')
  if (!insecure && (value('ADMIN_API_KEY') === 'changeme' || value('ADMIN_PASSWORD') === 'changeme')) {
    die('ADMIN_API_KEY / ADMIN_PASSWORD are still "changeme". Set real values in .env or pass --allow-insecure.')
  }

  if (token && accountId) {
    const d1Id = await ensureD1(token, accountId)
    patchD1Id(d1Id)
    await ensureR2(token, accountId, R2_NAME)
  } else {
    log('Skipping D1/R2 provisioning (no token) — run: npx wrangler d1 create virtual-professor-db and paste its id.')
  }

  if (token && accountId) {
    await uploadAvatar(token, accountId)
  }

  const cors = corsFlag()
  if (cors) {
    const toml = readFileSync(WRANGLER_TOML, 'utf8')
    const next = toml.replace(
      /(CORS_ORIGINS\s*=\s*")[^"]*(")/,
      `$1${JSON.stringify([cors, 'http://localhost:3000'])}$2`,
    )
    if (next !== toml) {
      writeFileSync(WRANGLER_TOML, next)
      log(`CORS_ORIGINS -> ${cors}`)
    }
  }

  log('Applying remote D1 migrations...')
  await run('npx.cmd', ['wrangler', 'd1', 'migrations', 'apply', D1_NAME, '--remote']).catch((err) =>
    die(`Migrations failed: ${err.message}`),
  )

  log('Deploying worker (creating initial deployment)...')
  await run('npx.cmd', ['wrangler', 'deploy']).catch((err) =>
    die(`Deploy failed: ${err.message}`),
  )

  log('Uploading secrets...')
  for (const name of SECRET_NAMES) {
    const secretValue = value(name)
    if (secretValue === undefined) {
      log(`Skipping secret ${name} (not set in .env)`)
      continue
    }
    await run('npx.cmd', ['wrangler', 'secret', 'put', name], { input: `${secretValue}\n` }).catch((err) =>
      die(`Secret ${name} failed: ${err.message}`),
    )
    log(`Secret ${name} set`)
  }

  log('Deploy finished. Worker is live.')
}

main().catch((err) => die(err instanceof Error ? err.message : String(err)))