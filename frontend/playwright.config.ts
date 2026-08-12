import { defineConfig, devices } from '@playwright/test'

const inCi = Boolean(process.env.CI)
const pythonCommand = process.env.DOCUFORGE_PYTHON?.trim() || 'python'

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  fullyParallel: false,
  forbidOnly: inCi,
  retries: inCi ? 1 : 0,
  workers: inCi ? 1 : undefined,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    acceptDownloads: true,
    trace: inCi ? 'on-first-retry' : 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `${pythonCommand} -m uvicorn docuforge.api.app:app --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: !inCi,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
      cwd: '.',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !inCi,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
