import { expect, expectDownload, openTool, test, visitCatalog } from './support'

const workflows = [
  { title: 'Word to PDF', kind: 'docx', label: 'Word document' },
  { title: 'PowerPoint to PDF', kind: 'pptx', label: 'PowerPoint presentation' },
  { title: 'Excel to PDF', kind: 'xlsx', label: 'Excel workbook' },
] as const

for (const workflow of workflows) {
  test(`${workflow.title} submits one file and downloads a PDF`, async ({ page }) => {
    await visitCatalog(page)
    const endpoint = `**/api/v1/office/${workflow.kind}-to-pdf`
    let requests = 0
    await page.route(endpoint, async (route) => {
      requests += 1
      expect(route.request().method()).toBe('POST')
      expect(route.request().postData()).toContain('name="file"')
      expect(route.request().postData()).toContain(`proposal.${workflow.kind}`)
      await route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        headers: { 'content-disposition': 'attachment; filename="proposal.pdf"' },
        body: Buffer.from('%PDF-1.7\nmocked Office result'),
      })
    })

    await openTool(page, workflow.title)
    await page.getByLabel(workflow.label).setInputFiles({
      name: `proposal.${workflow.kind}`,
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('test upload'),
    })
    await expectDownload(
      page,
      () => page.getByRole('button', { name: 'Convert to PDF' }).click(),
      /^proposal\.pdf$/,
    )
    expect(requests).toBe(1)
  })
}
