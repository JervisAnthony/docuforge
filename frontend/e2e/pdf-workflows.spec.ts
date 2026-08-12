import { expect, expectDownload, fixturePaths, openTool, returnToCatalog, test, visitCatalog } from './support'

test.beforeEach(async ({ page }) => {
  await visitCatalog(page)
})

test('catalog exposes ten connected operational tools', async ({ page }) => {
  await expect(page.getByLabel('DocuForge home')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(10)
  await expect(page.getByRole('button', { name: /^Open / })).toHaveCount(10)
})

test('Merge PDF downloads an ordered result', async ({ page }) => {
  await openTool(page, 'Merge PDF')
  await page.getByLabel('PDF files').setInputFiles([fixturePaths.onePageA, fixturePaths.onePageB])
  const items = page.getByRole('listitem')
  await expect(items).toHaveCount(2)
  await expect(items.nth(0)).toContainText('one-a.pdf')
  await expect(items.nth(1)).toContainText('one-b.pdf')
  await expectDownload(page, () => page.getByRole('button', { name: 'Merge PDFs' }).click(), /^merged\.pdf$/)
  await returnToCatalog(page)
})

test('Split PDF downloads a ZIP', async ({ page }) => {
  await openTool(page, 'Split PDF')
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await expectDownload(page, () => page.getByRole('button', { name: 'Split PDF' }).click(), /-pages\.zip$/)
})

test('Rotate PDF uses structured controls and downloads a PDF', async ({ page }) => {
  await openTool(page, 'Rotate PDF')
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await page.getByLabel('Page 1').fill('2')
  await page.getByLabel('Rotation', { exact: true }).selectOption('90')
  await expectDownload(page, () => page.getByRole('button', { name: 'Rotate PDF' }).click(), /-rotated\.pdf$/)
})

test('Remove pages uses the page-list UI and downloads a PDF', async ({ page }) => {
  await openTool(page, 'Remove pages')
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await page.getByLabel('Page numbers').fill('2')
  await expectDownload(page, () => page.getByRole('button', { name: 'Remove pages' }).click(), /-trimmed\.pdf$/)
})

test('Extract pages accepts order-sensitive input and downloads a PDF', async ({ page }) => {
  await openTool(page, 'Extract pages')
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await page.getByLabel('Page numbers').fill('3,1')
  await expectDownload(page, () => page.getByRole('button', { name: 'Extract pages' }).click(), /-extracted\.pdf$/)
})

test('PDF to images downloads a PNG ZIP', async ({ page }) => {
  await openTool(page, 'PDF to images')
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await page.getByLabel('Image format').selectOption('png')
  await page.getByLabel('Resolution (DPI)').fill('72')
  await expectDownload(
    page,
    () => page.getByRole('button', { name: 'Convert PDF to images' }).click(),
    /-images\.zip$/,
  )
})
