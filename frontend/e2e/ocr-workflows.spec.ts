import { expect, expectDownload, openTool, test, visitCatalog } from './support'

test('Image to Text displays OCR text and offers the exact TXT download', async ({ page }) => {
  await visitCatalog(page)
  await expect(page.getByRole('region', { name: 'OCR tools' })).toBeVisible()
  let requests = 0
  await page.route('**/api/v1/ocr/image-to-text', async (route) => {
    requests += 1
    expect(route.request().method()).toBe('POST')
    expect(route.request().postData()).toContain('name="file"')
    await route.fulfill({
      status: 200,
      contentType: 'text/plain; charset=utf-8',
      headers: { 'content-disposition': 'attachment; filename="receipt.txt"' },
      body: Buffer.from('Café\nsecond line\n'),
    })
  })
  await openTool(page, 'Image to Text')
  await page.getByLabel('Image', { exact: true }).setInputFiles({
    name: 'receipt.png', mimeType: 'image/png', buffer: Buffer.from('image fixture'),
  })
  await page.getByRole('button', { name: 'Extract text' }).click()
  await expect(page.getByLabel('Extracted text')).toHaveValue('Café\nsecond line\n')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download text' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('receipt.txt')
  expect(await download.failure()).toBeNull()
  expect(requests).toBe(1)
})

test('Scanned PDF to Text displays ordered multipage text', async ({ page }) => {
  await visitCatalog(page)
  let requests = 0
  await page.route('**/api/v1/ocr/pdf-to-text', async (route) => {
    requests += 1
    expect(route.request().method()).toBe('POST')
    expect(route.request().postData()).toContain('name="file"')
    await route.fulfill({
      status: 200,
      contentType: 'text/plain; charset=utf-8',
      headers: { 'content-disposition': 'attachment; filename="scan.txt"' },
      body: Buffer.from('first page\n\f第二頁\n'),
    })
  })
  await openTool(page, 'Scanned PDF to Text')
  await page.getByLabel('Scanned PDF', { exact: true }).setInputFiles({
    name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 fixture'),
  })
  await page.getByRole('button', { name: 'Extract text' }).click()
  await expect(page.getByLabel('Extracted text')).toHaveValue('first page\n\f第二頁\n')
  await expect(page.getByRole('button', { name: 'Download text' })).toBeEnabled()
  expect(requests).toBe(1)
})

test('Searchable PDF downloads the reconstructed PDF filename', async ({ page }) => {
  await visitCatalog(page)
  let requests = 0
  await page.route('**/api/v1/ocr/pdf-to-searchable-pdf', async (route) => {
    requests += 1
    expect(route.request().method()).toBe('POST')
    expect(route.request().postData()).toContain('name="file"')
    await route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      headers: { 'content-disposition': 'attachment; filename="scan-searchable.pdf"' },
      body: Buffer.from('%PDF-1.7\nmocked searchable result'),
    })
  })
  await openTool(page, 'Searchable PDF')
  await page.getByLabel('Scanned PDF', { exact: true }).setInputFiles({
    name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 fixture'),
  })
  await expectDownload(
    page, () => page.getByRole('button', { name: 'Make searchable' }).click(),
    /^scan-searchable\.pdf$/,
  )
  expect(requests).toBe(1)
})
