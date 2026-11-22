import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { buildIdentityPlugin, resolveRevision } from './build-identity.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), [
    'VITE_API_PROXY_TARGET', 'DOCUFORGE_BUILD_REVISION', 'VERCEL_GIT_COMMIT_SHA',
  ])
  const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))
  const revision = resolveRevision(env.DOCUFORGE_BUILD_REVISION, env.VERCEL_GIT_COMMIT_SHA)
  const proxyTarget =
    env.VITE_API_PROXY_TARGET?.trim() || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), buildIdentityPlugin(version, revision)],
    server: {
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      include: ['src/**/*.test.{ts,tsx}'],
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      css: true,
      restoreMocks: true,
    },
  }
})
