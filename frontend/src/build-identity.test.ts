import { afterEach, describe, expect, it, vi } from 'vitest'
import { build, preview } from 'vite'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { resolveRevision } from '../build-identity'

const revision = 'a1'.repeat(20)
const directories: string[] = []
afterEach(async () => {
  vi.unstubAllEnvs()
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})

describe('build revision sources', () => {
  it('supports missing, explicit, provider and normalized matching sources', () => {
    expect(resolveRevision()).toBeNull()
    expect(resolveRevision(revision.toUpperCase())).toBe(revision)
    expect(resolveRevision(undefined, revision)).toBe(revision)
    expect(resolveRevision(revision, revision.toUpperCase())).toBe(revision)
  })
  it.each(['', ' ', 'main', 'unknown', 'abc123', '0'.repeat(40), 'g'.repeat(40), revision + '\n', '\t' + revision, '０'.repeat(40)])(
    'rejects invalid or blank source %j', (value) => {
      expect(() => resolveRevision(value)).toThrow('Build revision')
      expect(() => resolveRevision(revision, value)).toThrow('Build revision')
    },
  )
  it('rejects disagreement', () => {
    expect(() => resolveRevision(revision, 'b'.repeat(40))).toThrow('Conflicting')
  })
})

it('emits matching built JSON/HTML and clears a previous stamp in a later unknown build', async () => {
  const outDir = await mkdtemp(join(tmpdir(), 'docuforge-identity-'))
  directories.push(outDir)
  for (const source of [revision, null]) {
    vi.stubEnv('DOCUFORGE_BUILD_REVISION', source?.toUpperCase())
    vi.stubEnv('VERCEL_GIT_COMMIT_SHA', source ?? undefined)
    await build({
      logLevel: 'silent',
      build: { outDir, emptyOutDir: true },
    })
    const manifest = JSON.parse(await readFile(join(outDir, 'build-info.json'), 'utf8'))
    const html = await readFile(join(outDir, 'index.html'), 'utf8')
    expect(manifest).toEqual({ schema_version: 1, service: 'docuforge-frontend', version: '0.1.0', revision: source })
    expect(html.match(/name="docuforge-version"/g)).toHaveLength(1)
    expect(html.match(/name="docuforge-revision"/g)).toHaveLength(1)
    expect(html).toContain('name="docuforge-version" content="0.1.0"')
    expect(html).toContain(`name="docuforge-revision" content="${source ?? 'unknown'}"`)
  }
  const server = await preview({ configFile: false, build: { outDir }, preview: { host: '127.0.0.1', port: 0 } })
  try {
    const response = await fetch(new URL('/build-info.json', server.resolvedUrls!.local[0]))
    expect(response.headers.get('content-type')).toContain('application/json')
    expect((await response.json()).revision).toBeNull()
  } finally {
    await new Promise<void>((resolve, reject) => server.httpServer.close((error) => error ? reject(error) : resolve()))
  }
}, 60000)

it('keeps identity out of SPA fallback and scopes no-store to the JSON', async () => {
  const config = JSON.parse(await readFile('vercel.json', 'utf8'))
  const spa = new RegExp(`^${config.rewrites[0].source}$`)
  expect(spa.test('/build-info.json')).toBe(false)
  expect(spa.test('/tools/pdf-merge')).toBe(true)
  expect(config.headers).toEqual([{ source: '/build-info.json', headers: [{ key: 'Cache-Control', value: 'no-store' }] }])
})
