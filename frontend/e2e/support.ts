import { stat } from 'node:fs/promises'
import path from 'node:path'
import { expect, test as base } from '@playwright/test'
import type { Page } from '@playwright/test'

export const fixturePaths = {
  onePageA: path.resolve('.e2e-fixtures', 'one-a.pdf'),
  onePageB: path.resolve('.e2e-fixtures', 'one-b.pdf'),
  threePages: path.resolve('.e2e-fixtures', 'three-pages.pdf'),
  sourcePng: path.resolve('.e2e-fixtures', 'source.png'),
  portraitPng: path.resolve('.e2e-fixtures', 'portrait.png'),
  landscapePng: path.resolve('.e2e-fixtures', 'landscape.png'),
  compressibleJpeg: path.resolve('.e2e-fixtures', 'compressible.jpg'),
  corruptPng: path.resolve('.e2e-fixtures', 'corrupt.png'),
  corruptPdf: path.resolve('.e2e-fixtures', 'corrupt.pdf'),
} as const

export const test = base.extend<{ unexpectedBrowserErrors: void }>({
  unexpectedBrowserErrors: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
      page.on('console', (message) => {
        const isExpectedProcessingRejection =
          message.text() ===
          'Failed to load resource: the server responded with a status of 422 (Unprocessable Content)'
        if (message.type() === 'error' && !isExpectedProcessingRejection) {
          errors.push(`console: ${message.text()}`)
        }
      })
      await use()
      expect(errors, 'unexpected browser errors').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

export async function visitCatalog(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Choose the right tool for your file' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('API connected')
}

export async function openTool(page: Page, name: string) {
  await page.getByRole('button', { name: `Open ${name}` }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeFocused()
}

export async function returnToCatalog(page: Page) {
  await page.getByRole('button', { name: /Back to tools/ }).click()
  await expect(page.getByRole('heading', { name: 'Choose the right tool for your file' })).toBeVisible()
}

export async function expectDownload(
  page: Page,
  action: () => Promise<void>,
  filename: RegExp,
) {
  const [download] = await Promise.all([page.waitForEvent('download'), action()])
  expect(download.suggestedFilename()).toMatch(filename)
  expect(await download.failure()).toBeNull()
  const downloadPath = await download.path()
  expect(downloadPath).not.toBeNull()
  expect((await stat(downloadPath!)).size).toBeGreaterThan(0)
  await expect(page.getByText(/Complete\. Downloaded .+\./)).toBeVisible()
  return download
}
