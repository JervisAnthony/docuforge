import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { OfficeToPdfForm } from './OfficeToPdfForm'

const cases = [
  ['office-docx-to-pdf', 'Word document', '.docx', '/api/v1/office/docx-to-pdf'],
  ['office-pptx-to-pdf', 'PowerPoint presentation', '.pptx', '/api/v1/office/pptx-to-pdf'],
  ['office-xlsx-to-pdf', 'Excel workbook', '.xlsx', '/api/v1/office/xlsx-to-pdf'],
] as const

function successfulClient(filename = 'server-result.pdf'): MultipartRequestClient {
  return {
    postMultipartForBlob: vi.fn(async () => ({
      blob: new Blob(['%PDF-1.7'], { type: 'application/pdf' }),
      contentType: 'application/pdf',
      contentDisposition: `attachment; filename="${filename}"`,
    })),
  }
}

describe('OfficeToPdfForm', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:office-result'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each(cases)('submits one %s file to the matching API route', async (toolId, label, extension, endpoint) => {
    const user = userEvent.setup()
    const client = successfulClient()
    render(<OfficeToPdfForm toolId={toolId} client={client} />)
    const input = screen.getByLabelText(label)
    expect(input).toHaveAttribute('accept', extension)
    expect(screen.getByRole('button', { name: 'Convert to PDF' })).toBeDisabled()
    await user.upload(input, new File(['fixture'], `Quarterly Report${extension.toUpperCase()}`))
    await user.click(screen.getByRole('button', { name: 'Convert to PDF' }))
    const [actualEndpoint, formData] = vi.mocked(client.postMultipartForBlob).mock.calls[0]
    expect(actualEndpoint).toBe(endpoint)
    expect(Array.from(formData.keys())).toEqual(['file'])
    expect((formData.get('file') as File).name).toBe(`Quarterly Report${extension.toUpperCase()}`)
    expect(await screen.findByText('Complete. Downloaded server-result.pdf.')).toBeVisible()
  })

  it.each(cases)('rejects a wrong extension for %s', async (toolId, label, extension) => {
    const user = userEvent.setup({ applyAccept: false })
    const client = successfulClient()
    render(<OfficeToPdfForm toolId={toolId} client={client} />)
    await user.upload(screen.getByLabelText(label), new File(['wrong'], 'wrong.txt'))
    expect(screen.getByText(`Choose a ${extension} file.`)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Convert to PDF' })).toBeDisabled()
    expect(client.postMultipartForBlob).not.toHaveBeenCalled()
  })

  it('shows the safe API error and permits clearing the selected file', async () => {
    const user = userEvent.setup()
    const client: MultipartRequestClient = {
      postMultipartForBlob: vi.fn(async () => {
        throw new ApiClientError('Office conversion is temporarily unavailable.', {
          kind: 'http', status: 503, code: 'office_engine_unavailable',
        })
      }),
    }
    render(<OfficeToPdfForm toolId="office-docx-to-pdf" client={client} />)
    await user.upload(screen.getByLabelText('Word document'), new File(['doc'], 'source.docx'))
    await user.click(screen.getByRole('button', { name: 'Convert to PDF' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Office conversion is temporarily unavailable.',
    )
    await user.click(screen.getByRole('button', { name: 'Clear file' }))
    expect(screen.getByRole('button', { name: 'Convert to PDF' })).toBeDisabled()
  })
})
