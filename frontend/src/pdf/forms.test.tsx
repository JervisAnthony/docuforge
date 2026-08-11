import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import { ExtractPagesPdfForm } from './ExtractPagesPdfForm'
import { MergePdfForm } from './MergePdfForm'
import { PdfToImagesForm } from './PdfToImagesForm'
import { RemovePagesPdfForm } from './RemovePagesPdfForm'
import { RotatePdfForm } from './RotatePdfForm'
import { SplitPdfForm } from './SplitPdfForm'
import type { PdfRequestClient } from './types'

function pdf(name: string, content = name) {
  return new File([content], name, { type: 'application/pdf' })
}

function successfulClient(
  contentDisposition: string | null = 'attachment; filename="result.pdf"',
): PdfRequestClient {
  return {
    postMultipartForBlob: vi.fn(async () => ({
      blob: new Blob(['result']),
      contentType: 'application/pdf',
      contentDisposition,
    })),
  }
}

function requestMock(client: PdfRequestClient) {
  return vi.mocked(client.postMultipartForBlob)
}

describe('PDF workflow forms', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:pdf-result'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('merge', () => {
    it('requires two PDFs, preserves selection order, and submits repeated files', async () => {
      const user = userEvent.setup()
      const client = successfulClient('attachment; filename="joined.pdf"')
      render(<MergePdfForm client={client} />)
      const input = screen.getByLabelText('PDF files')
      const first = pdf('first.pdf')
      const second = pdf('second.pdf')

      expect(screen.getByRole('button', { name: 'Merge PDFs' })).toBeDisabled()
      await user.upload(input, first)
      expect(screen.getByText('Select at least two PDF files.')).toBeVisible()
      await user.upload(input, [first, second])

      const list = screen.getByRole('list')
      expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        expect.stringContaining('first.pdf'),
        expect.stringContaining('second.pdf'),
      ])

      await user.click(screen.getByRole('button', { name: 'Merge PDFs' }))
      await waitFor(() => expect(requestMock(client)).toHaveBeenCalledOnce())
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/merge')
      expect((formData.getAll('files') as File[]).map((file) => file.name)).toEqual([
        'first.pdf',
        'second.pdf',
      ])
      expect(await screen.findByText('Complete. Downloaded joined.pdf.')).toBeVisible()
    })

    it('reorders and removes files accessibly, matching multipart order', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<MergePdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF files'), [pdf('a.pdf'), pdf('b.pdf')])
      await user.click(screen.getByRole('button', { name: 'Move b.pdf up' }))
      await user.click(screen.getByRole('button', { name: 'Merge PDFs' }))
      const formData = requestMock(client).mock.calls[0][1]
      expect((formData.getAll('files') as File[]).map((file) => file.name)).toEqual([
        'b.pdf',
        'a.pdf',
      ])
      await user.click(screen.getByRole('button', { name: 'Remove a.pdf' }))
      expect(screen.getByText('Select at least two PDF files.')).toBeVisible()
    })

    it('uses the merge fallback filename when the server omits one', async () => {
      const user = userEvent.setup()
      const client = successfulClient(null)
      render(<MergePdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF files'), [pdf('a.pdf'), pdf('b.pdf')])
      await user.click(screen.getByRole('button', { name: 'Merge PDFs' }))
      expect(await screen.findByText('Complete. Downloaded merged.pdf.')).toBeVisible()
    })

    it('locks submission while pending and shows a safe backend error', async () => {
      const user = userEvent.setup()
      let rejectRequest: (reason: unknown) => void = () => undefined
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(
          () =>
            new Promise<never>((_, reject) => {
              rejectRequest = reject
            }),
        ),
      }
      render(<MergePdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF files'), [pdf('a.pdf'), pdf('b.pdf')])
      await user.click(screen.getByRole('button', { name: 'Merge PDFs' }))
      expect(screen.getByRole('button', { name: 'Processing…' })).toBeDisabled()
      await act(async () => {
        rejectRequest(
          new ApiClientError('The upload is too large.', {
            kind: 'http',
            status: 413,
            code: 'upload_too_large',
          }),
        )
      })
      expect(await screen.findByRole('alert')).toHaveTextContent('The upload is too large.')
    })
  })

  describe('split', () => {
    it('submits one file to the split endpoint and downloads a ZIP', async () => {
      const user = userEvent.setup()
      const client = successfulClient(null)
      render(<SplitPdfForm client={client} />)
      expect(screen.getByRole('button', { name: 'Split PDF' })).toBeDisabled()
      await user.upload(screen.getByLabelText('PDF file'), pdf('book.pdf'))
      await user.click(screen.getByRole('button', { name: 'Split PDF' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/split')
      expect((formData.get('file') as File).name).toBe('book.pdf')
      expect(await screen.findByText('Complete. Downloaded split-pages.zip.')).toBeVisible()
    })

    it('handles a network failure without exposing internals', async () => {
      const user = userEvent.setup()
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('The DocuForge API could not be reached.', { kind: 'network' })
        }),
      }
      render(<SplitPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('book.pdf'))
      await user.click(screen.getByRole('button', { name: 'Split PDF' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The DocuForge API could not be reached.',
      )
    })

    it('shows a safe backend split error', async () => {
      const user = userEvent.setup()
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('The PDF could not be processed.', {
            kind: 'http',
            status: 422,
            code: 'pdf_processing_failed',
          })
        }),
      }
      render(<SplitPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('broken.pdf'))
      await user.click(screen.getByRole('button', { name: 'Split PDF' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('The PDF could not be processed.')
    })
  })

  describe('rotate', () => {
    it('validates structured rows and serializes repeated rotations exactly', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<RotatePdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('pages.pdf'))
      expect(screen.getByRole('button', { name: 'Rotate PDF' })).toBeDisabled()
      await user.type(screen.getByLabelText('Page 1'), '2')
      await user.click(screen.getByRole('button', { name: 'Add page rotation' }))
      await user.type(screen.getByLabelText('Page 2'), '4')
      await user.selectOptions(screen.getByLabelText('Rotation', { selector: '#rotation-degrees-2' }), '270')
      await user.click(screen.getByRole('button', { name: 'Rotate PDF' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/rotate')
      expect(formData.getAll('rotate')).toEqual(['2:90', '4:270'])
    })

    it('rejects invalid and duplicate pages and supports row removal', async () => {
      const user = userEvent.setup()
      render(<RotatePdfForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('pages.pdf'))
      await user.type(screen.getByLabelText('Page 1'), '0')
      expect(screen.getByText('Every page must be a positive whole number.')).toBeVisible()
      await user.clear(screen.getByLabelText('Page 1'))
      await user.type(screen.getByLabelText('Page 1'), '2')
      await user.click(screen.getByRole('button', { name: 'Add page rotation' }))
      await user.type(screen.getByLabelText('Page 2'), '2')
      expect(screen.getByText('Page 2 has more than one rotation instruction.')).toBeVisible()
      await user.click(screen.getByRole('button', { name: 'Remove rotation row 2' }))
      expect(screen.queryByLabelText('Page 2')).not.toBeInTheDocument()
    })

    it('shows a safe rotation API failure', async () => {
      const user = userEvent.setup()
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('A selected page is outside the document.', {
            kind: 'http',
            status: 422,
            code: 'pdf_processing_failed',
          })
        }),
      }
      render(<RotatePdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('pages.pdf'))
      await user.type(screen.getByLabelText('Page 1'), '99')
      await user.click(screen.getByRole('button', { name: 'Rotate PDF' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'A selected page is outside the document.',
      )
    })
  })

  describe('page selection', () => {
    it('preserves remove-page field order', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<RemovePagesPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      await user.type(screen.getByLabelText('Page numbers'), '4,2,5')
      await user.click(screen.getByRole('button', { name: 'Remove pages' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/remove-pages')
      expect(formData.getAll('page')).toEqual(['4', '2', '5'])
      expect(await screen.findByText('Complete. Downloaded result.pdf.')).toBeVisible()
    })

    it('preserves extract order and displays parser validation', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<ExtractPagesPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      await user.type(screen.getByLabelText('Page numbers'), '2-4')
      expect(
        screen.getByText(
          'Use positive whole page numbers separated by commas; ranges are not supported.',
        ),
      ).toBeVisible()
      await user.clear(screen.getByLabelText('Page numbers'))
      await user.type(screen.getByLabelText('Page numbers'), '4,2,5')
      await user.click(screen.getByRole('button', { name: 'Extract pages' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/extract-pages')
      expect(formData.getAll('page')).toEqual(['4', '2', '5'])
    })

    it('shows errors for remove and extract operations', async () => {
      const user = userEvent.setup()
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('The page selection is not valid for this PDF.', {
            kind: 'http',
            status: 422,
            code: 'pdf_processing_failed',
          })
        }),
      }
      const { unmount } = render(<RemovePagesPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      await user.type(screen.getByLabelText('Page numbers'), '9')
      await user.click(screen.getByRole('button', { name: 'Remove pages' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The page selection is not valid for this PDF.',
      )
      unmount()

      render(<ExtractPagesPdfForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      await user.type(screen.getByLabelText('Page numbers'), '9')
      await user.click(screen.getByRole('button', { name: 'Extract pages' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The page selection is not valid for this PDF.',
      )
    })
  })

  describe('PDF to images', () => {
    it('offers only supported formats and submits default DPI 150', async () => {
      const user = userEvent.setup()
      const client = successfulClient('attachment; filename="pages.zip"')
      render(<PdfToImagesForm client={client} />)
      const format = screen.getByLabelText('Image format')
      expect(within(format).getAllByRole('option').map((option) => option.textContent)).toEqual([
        'JPEG',
        'PNG',
        'WebP',
        'BMP',
        'TIFF',
      ])
      expect(screen.getByLabelText('Resolution (DPI)')).toHaveValue(150)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      await user.selectOptions(format, 'tiff')
      await user.click(screen.getByRole('button', { name: 'Convert PDF to images' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/pdf/to-images')
      expect(formData.get('format')).toBe('tiff')
      expect(formData.get('dpi')).toBe('150')
      expect(await screen.findByText('Complete. Downloaded pages.zip.')).toBeVisible()
    })

    it.each([
      ['72', true],
      ['300', true],
      ['71', false],
      ['301', false],
      ['1.5', false],
    ])('validates DPI %s', async (dpi, valid) => {
      const user = userEvent.setup()
      render(<PdfToImagesForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('source.pdf'))
      fireEvent.change(screen.getByLabelText('Resolution (DPI)'), { target: { value: dpi } })
      const submit = screen.getByRole('button', { name: 'Convert PDF to images' })
      if (valid) {
        expect(submit).toBeEnabled()
      } else {
        expect(submit).toBeDisabled()
      }
    })

    it('shows a safe backend rendering error', async () => {
      const user = userEvent.setup()
      const client: PdfRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('The PDF could not be rendered.', {
            kind: 'http',
            status: 422,
            code: 'pdf_processing_failed',
          })
        }),
      }
      render(<PdfToImagesForm client={client} />)
      await user.upload(screen.getByLabelText('PDF file'), pdf('broken.pdf'))
      await user.click(screen.getByRole('button', { name: 'Convert PDF to images' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('The PDF could not be rendered.')
    })
  })
})
