import { expect, expectDownload, fixturePaths, openTool, returnToCatalog, test, visitCatalog } from './support'

test('invalid forms remain client-side and expose accessible validation', async ({ page }) => {
  const posts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') posts.push(request.url())
  })
  await visitCatalog(page)

  await openTool(page, 'Merge PDF')
  await page.getByLabel('PDF files').setInputFiles(fixturePaths.onePageA)
  await expect(page.getByText('Select at least two PDF files.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Merge PDFs' })).toBeDisabled()
  await returnToCatalog(page)

  await openTool(page, 'Resize image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await expect(page.getByText('Enter a maximum width or height.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resize image' })).toBeDisabled()
  await returnToCatalog(page)

  await openTool(page, 'Compress image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await expect(page.getByText('Quality compression is available for JPEG and WebP.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Compress image' })).toBeDisabled()
  expect(posts).toEqual([])
})

test('a corrupt image can be corrected, repeated, then followed by a PDF workflow', async ({ page }) => {
  await visitCatalog(page)
  await openTool(page, 'Convert image')
  await page.getByLabel('Image file').setInputFiles(fixturePaths.corruptPng)
  await page.getByRole('button', { name: 'Convert image' }).click()
  await expect(page.getByRole('alert')).toContainText('The image could not be processed.')

  await page.getByLabel('Image file').setInputFiles(fixturePaths.sourcePng)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByLabel('Target format').selectOption('webp')
  await expectDownload(page, () => page.getByRole('button', { name: 'Convert image' }).click(), /-converted\.webp$/)
  await page.getByLabel('Target format').selectOption('jpeg')
  await expect(page.getByText(/Complete\. Downloaded .+\./)).toHaveCount(0)
  await page.getByLabel('Target format').selectOption('webp')
  await expectDownload(page, () => page.getByRole('button', { name: 'Convert image' }).click(), /-converted\.webp$/)

  await returnToCatalog(page)
  await openTool(page, 'Split PDF')
  await expect(page.getByText('source.png')).toHaveCount(0)
  await page.getByLabel('PDF file').setInputFiles(fixturePaths.threePages)
  await expectDownload(page, () => page.getByRole('button', { name: 'Split PDF' }).click(), /-pages\.zip$/)
})

test('mobile-width catalog and representative workspaces do not overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await visitCatalog(page)
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
  expect(hasHorizontalOverflow).toBe(false)

  await openTool(page, 'Merge PDF')
  await expect(page.getByLabel('PDF files')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Merge PDFs' })).toBeVisible()
  await returnToCatalog(page)
  await openTool(page, 'Convert image')
  await expect(page.getByLabel('Image file')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Convert image' })).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false)
})
