import type { Plugin } from 'vite'

export function resolveRevision(explicit?: string, provider?: string): string | null {
  const values = [explicit, provider].filter((value) => value !== undefined)
  for (const value of values) {
    if (value.length !== 40 || !/^[a-fA-F0-9]{40}$/.test(value) || value === '0'.repeat(40)) {
      throw new Error('Build revision must be a full forty-character hexadecimal Git SHA')
    }
  }
  const normalized = values.map((value) => value.toLowerCase())
  if (new Set(normalized).size > 1) throw new Error('Conflicting build revision sources')
  return normalized[0] ?? null
}

export function buildIdentityPlugin(version: string, revision: string | null): Plugin {
  const identity = { schema_version: 1, service: 'docuforge-frontend', version, revision }
  return {
    name: 'docuforge-build-identity',
    apply: 'build',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'build-info.json',
        source: JSON.stringify(identity) + '\n',
      })
    },
    transformIndexHtml() {
      return [
        { tag: 'meta', attrs: { name: 'docuforge-version', content: identity.version }, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'docuforge-revision', content: identity.revision ?? 'unknown' }, injectTo: 'head' },
      ]
    },
  }
}
