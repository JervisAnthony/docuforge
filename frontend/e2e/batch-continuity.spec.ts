import { expect, fixturePaths, openTool, returnToCatalog, test, visitCatalog } from './support'

for (const reload of [false, true]) {
  test(`Batch resumes after ${reload ? 'reload with an explicitly copied key' : 'catalog navigation'}`, async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await visitCatalog(page)
    await openTool(page, 'Batch image convert')
    await page.getByLabel('Image files').setInputFiles(fixturePaths.sourcePng)
    const accepted = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/v1/batches/images/convert'))
    await page.getByRole('button', { name: 'Start batch' }).click()
    const payload = await (await accepted).json()
    const batchId = payload.id
    await expect(page.getByRole('button', { name: 'Download ZIP' })).toBeEnabled()
    let key = ''
    if (reload) {
      await page.getByRole('button', { name: 'Copy recovery key' }).click()
      await expect(page.getByText('Recovery key copied. Keep it private.')).toBeVisible()
      key = await page.evaluate(() => navigator.clipboard.readText())
      expect(key.startsWith(`DFB1:${batchId}:`)).toBe(true)
      await page.reload()
    } else {
      await returnToCatalog(page)
    }
    const statusResponse = page.waitForResponse((response) => response.request().method() === 'GET' && response.url().endsWith(`/api/v1/batches/${batchId}`))
    await openTool(page, 'Batch image convert')
    if (reload) {
      await page.getByRole('button', { name: 'Resume a batch' }).click()
      await page.getByLabel('Recovery key').fill(key)
      await page.getByRole('button', { name: 'Resume', exact: true }).click()
    }
    const refreshed = await statusResponse
    expect(refreshed.ok()).toBe(true)
    expect((await refreshed.json()).id).toBe(batchId)
    if (reload) expect(refreshed.request().headers()['x-docuforge-batch-token']).toBe(key.split(':')[2])
    await expect(page.getByRole('button', { name: 'Download ZIP' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Start batch' })).toHaveCount(0)
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download ZIP' }).click()
    expect((await download).suggestedFilename()).toContain(batchId)
    await page.getByRole('button', { name: 'Delete batch' }).click()
    await page.getByRole('button', { name: 'Delete now' }).click()
    await expect(page.getByText('Batch deleted from the server.')).toBeVisible()
  })
}
