import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { OcrSearchablePdfForm } from './OcrSearchablePdfForm'

describe('OcrSearchablePdfForm', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:ocr-pdf'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('submits one uppercase PDF and downloads the returned artifact', async () => {
    const user = userEvent.setup()
    const blob = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    const client: MultipartRequestClient = {
      postMultipartForBlob: vi.fn(async () => ({
        blob, contentType: 'application/pdf',
        contentDisposition: 'attachment; filename="server-searchable.pdf"',
      })),
    }
    render(<OcrSearchablePdfForm client={client} />)
    await user.upload(screen.getByLabelText('Scanned PDF'), new File(['pdf'], 'scan.PDF'))
    await user.click(screen.getByRole('button', { name: 'Make searchable' }))
    const [endpoint, formData] = vi.mocked(client.postMultipartForBlob).mock.calls[0]
    expect(endpoint).toBe('/api/v1/ocr/pdf-to-searchable-pdf')
    expect(Array.from(formData.keys())).toEqual(['file'])
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
    expect(await screen.findByText('Complete. Downloaded server-searchable.pdf.')).toBeVisible()
  })

  it('uses a safe fallback searchable filename and rejects wrong extensions', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const client: MultipartRequestClient = {
      postMultipartForBlob: vi.fn(async () => ({
        blob: new Blob(['%PDF-1.7']), contentType: 'application/pdf', contentDisposition: null,
      })),
    }
    render(<OcrSearchablePdfForm client={client} />)
    const input = screen.getByLabelText('Scanned PDF')
    await user.upload(input, new File(['image'], 'image.png'))
    expect(screen.getByRole('button', { name: 'Make searchable' })).toBeDisabled()
    await user.upload(input, new File(['pdf'], 'scan.pdf'))
    await user.click(screen.getByRole('button', { name: 'Make searchable' }))
    expect(await screen.findByText('Complete. Downloaded scan-searchable.pdf.')).toBeVisible()
  })

  it('surfaces API errors and hides unexpected details', async () => {
    const user = userEvent.setup()
    const client: MultipartRequestClient = {
      postMultipartForBlob: vi.fn()
        .mockRejectedValueOnce(new ApiClientError('The OCR operation timed out.', {
          kind: 'http', status: 504, code: 'ocr_timeout',
        }))
        .mockRejectedValueOnce(new Error('private path')),
    }
    render(<OcrSearchablePdfForm client={client} />)
    await user.upload(screen.getByLabelText('Scanned PDF'), new File(['pdf'], 'scan.pdf'))
    await user.click(screen.getByRole('button', { name: 'Make searchable' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The OCR operation timed out.')
    await user.click(screen.getByRole('button', { name: 'Make searchable' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The document could not be processed with OCR. Please try again.',
    )
  })
})
