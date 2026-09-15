import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import type { MultipartRequestClient } from '../workflows/useSubmission'
import { OcrTextForm } from './OcrTextForm'

const text = '  Café\nline two  \f第三頁\n'

function successfulClient(content = text): { client: MultipartRequestClient; blob: Blob } {
  const blob = new Blob([content], { type: 'text/plain' })
  return {
    blob,
    client: {
      postMultipartForBlob: vi.fn(async () => ({
        blob, contentType: 'text/plain; charset=utf-8',
        contentDisposition: 'attachment; filename="server-result.txt"',
      })),
    },
  }
}

describe('OcrTextForm', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:ocr-text'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each([
    ['ocr-image-to-text', 'Image', 'receipt.PNG', '/api/v1/ocr/image-to-text'],
    ['ocr-pdf-to-text', 'Scanned PDF', 'scan.PDF', '/api/v1/ocr/pdf-to-text'],
  ] as const)('submits %s and displays exact text before optional download', async (
    toolId, label, name, endpoint,
  ) => {
    const user = userEvent.setup()
    const { client, blob } = successfulClient()
    render(<OcrTextForm toolId={toolId} client={client} />)
    expect(screen.getByRole('button', { name: 'Extract text' })).toBeDisabled()
    await user.upload(screen.getByLabelText(label), new File(['input'], name))
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    const [actualEndpoint, formData] = vi.mocked(client.postMultipartForBlob).mock.calls[0]
    expect(actualEndpoint).toBe(endpoint)
    expect(Array.from(formData.keys())).toEqual(['file'])
    expect((formData.get('file') as File).name).toBe(name)
    const result = await screen.findByLabelText('Extracted text')
    expect(result).toHaveValue(text)
    expect(result).toHaveAttribute('readonly')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Download text' }))
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
  })

  it('accepts supported image aliases and rejects GIF/PDF client-side', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const { client } = successfulClient()
    render(<OcrTextForm toolId="ocr-image-to-text" client={client} />)
    const input = screen.getByLabelText('Image')
    expect(input).toHaveAttribute('accept', '.jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff')
    for (const name of ['bad.gif', 'bad.pdf']) {
      await user.upload(input, new File(['bad'], name))
      expect(screen.getByRole('button', { name: 'Extract text' })).toBeDisabled()
      expect(screen.getByText('Choose a supported image file.')).toBeVisible()
    }
    await user.upload(input, new File(['image'], 'good.JPEG'))
    expect(screen.getByRole('button', { name: 'Extract text' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Clear file' }))
    expect(screen.getByRole('button', { name: 'Extract text' })).toBeDisabled()
    expect(client.postMultipartForBlob).not.toHaveBeenCalled()
  })

  it('treats empty OCR text as success and keeps the downloadable artifact', async () => {
    const user = userEvent.setup()
    const { client, blob } = successfulClient('')
    render(<OcrTextForm toolId="ocr-pdf-to-text" client={client} />)
    await user.upload(screen.getByLabelText('Scanned PDF'), new File(['pdf'], 'blank.pdf'))
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    expect(await screen.findByText('No text was recognized in this document.')).toBeVisible()
    expect(screen.getByLabelText('Extracted text')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Download text' }))
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
  })

  it('surfaces safe API errors, uses fallback for unexpected errors, and clears old results', async () => {
    const user = userEvent.setup()
    const success = successfulClient()
    const client: MultipartRequestClient = {
      postMultipartForBlob: vi.fn()
        .mockImplementationOnce(success.client.postMultipartForBlob)
        .mockRejectedValueOnce(new ApiClientError('OCR is temporarily unavailable.', {
          kind: 'http', status: 503, code: 'ocr_engine_unavailable',
        }))
        .mockRejectedValueOnce(new Error('private path')),
    }
    render(<OcrTextForm toolId="ocr-image-to-text" client={client} />)
    const input = screen.getByLabelText('Image')
    await user.upload(input, new File(['a'], 'first.png'))
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    expect(await screen.findByLabelText('Extracted text')).toHaveValue(text)
    await user.upload(input, new File(['b'], 'second.png'))
    expect(screen.queryByLabelText('Extracted text')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('OCR is temporarily unavailable.')
    await user.click(screen.getByRole('button', { name: 'Extract text' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The document could not be processed with OCR. Please try again.',
    )
  })
})
