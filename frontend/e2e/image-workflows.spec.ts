import { expect, expectDownload, fixturePaths, openTool, test, visitCatalog } from './support'

test.beforeEach(async ({ page }) => {
  await visitCatalog(page)
})

test('Convert image downloads WebP', async ({ page }) => {
  await openTool(page, 'Convert image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await page.getByLabel('Target format').selectOption('webp')
  await expectDownload(page, () => page.getByRole('button', { name: 'Convert image' }).click(), /-converted\.webp$/)
})

test('Resize image downloads with no-upscale intentionally disabled', async ({ page }) => {
  await openTool(page, 'Resize image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await page.getByLabel('Maximum width').fill('80')
  await expect(page.getByRole('checkbox', { name: 'Allow upscaling' })).not.toBeChecked()
  await expectDownload(page, () => page.getByRole('button', { name: 'Resize image' }).click(), /-resized\.png$/)
})

test('Compress image quality mode downloads JPEG', async ({ page }) => {
  await openTool(page, 'Compress image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.compressibleJpeg)
  await expect(page.getByRole('radio', { name: 'Quality' })).toBeChecked()
  await page.getByRole('spinbutton', { name: 'Quality' }).fill('60')
  await expectDownload(page, () => page.getByRole('button', { name: 'Compress image' }).click(), /-compressed\.jpg$/)
})

test('Compress image maximum-size mode downloads within the real backend branch', async ({ page }) => {
  await openTool(page, 'Compress image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await page.getByRole('radio', { name: 'Maximum file size' }).check()
  await page.getByLabel('Maximum size (KB)').fill('50')
  await expectDownload(page, () => page.getByRole('button', { name: 'Compress image' }).click(), /-compressed\.png$/)
})

test('Images to PDF reorders pages and downloads a PDF', async ({ page }) => {
  await openTool(page, 'Images to PDF')
  await page.getByLabel('Image files').setInputFiles([fixturePaths.portraitPng, fixturePaths.landscapePng])
  await page.getByRole('button', { name: 'Move landscape.png up' }).click()
  const items = page.getByRole('listitem')
  await expect(items.nth(0)).toContainText('landscape.png')
  await expect(items.nth(1)).toContainText('portrait.png')
  await expectDownload(page, () => page.getByRole('button', { name: 'Create PDF' }).click(), /^images\.pdf$/)
})
