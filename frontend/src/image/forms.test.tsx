import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClientError } from '../api/client'
import { CompressImageForm } from './CompressImageForm'
import { ConvertImageForm } from './ConvertImageForm'
import { ImagesToPdfForm } from './ImagesToPdfForm'
import { ResizeImageForm } from './ResizeImageForm'
import type { ImageRequestClient } from './types'

function image(name: string, type = 'image/png') {
  return new File([name], name, { type })
}

function successfulClient(
  contentDisposition: string | null = 'attachment; filename="result.png"',
  contentType = 'image/png',
): ImageRequestClient {
  return {
    postMultipartForBlob: vi.fn(async () => ({
      blob: new Blob(['result'], { type: contentType }),
      contentType,
      contentDisposition,
    })),
  }
}

function failingClient(message: string): ImageRequestClient {
  return {
    postMultipartForBlob: vi.fn(async () => {
      throw new ApiClientError(message, {
        kind: 'http',
        status: 422,
        code: 'image_processing_failed',
      })
    }),
  }
}

function requestMock(client: ImageRequestClient) {
  return vi.mocked(client.postMultipartForBlob)
}

describe('image workflow forms', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:image-result'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('convert', () => {
    it('requires a file, exposes five formats, infers the source extension, and submits exactly', async () => {
      const user = userEvent.setup()
      const client = successfulClient('attachment; filename="safe-output.webp"', 'image/webp')
      render(<ConvertImageForm client={client} />)
      const input = screen.getByLabelText('Image file')
      expect(input).toHaveAttribute('accept', '.jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff')
      expect(screen.getByRole('button', { name: 'Convert image' })).toBeDisabled()
      await user.upload(input, image('graphic.png'))
      const format = screen.getByLabelText('Target format')
      expect(format).toHaveValue('png')
      expect(within(format).getAllByRole('option').map((option) => option.textContent)).toEqual([
        'Choose a format',
        'JPEG',
        'PNG',
        'WebP',
        'BMP',
        'TIFF',
      ])
      await user.selectOptions(format, 'webp')
      await user.click(screen.getByRole('button', { name: 'Convert image' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/images/convert')
      expect(Array.from(formData.keys())).toEqual(['file', 'format'])
      expect((formData.get('file') as File).name).toBe('graphic.png')
      expect(formData.get('format')).toBe('webp')
      expect(await screen.findByText('Complete. Downloaded safe-output.webp.')).toBeVisible()
    })

    it('rejects an unsupported input extension before submission', async () => {
      const user = userEvent.setup({ applyAccept: false })
      const client = successfulClient()
      render(<ConvertImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('animation.gif', 'image/gif'))
      expect(screen.getByText('Choose a JPEG, PNG, WebP, BMP, or TIFF file.')).toBeVisible()
      expect(screen.getByRole('button', { name: 'Convert image' })).toBeDisabled()
      expect(requestMock(client)).not.toHaveBeenCalled()
    })

    it.each([
      ['jpeg', 'converted-image.jpg'],
      ['png', 'converted-image.png'],
      ['webp', 'converted-image.webp'],
      ['bmp', 'converted-image.bmp'],
      ['tiff', 'converted-image.tiff'],
    ])('uses the canonical %s fallback filename', async (format, fallback) => {
      const user = userEvent.setup()
      render(<ConvertImageForm client={successfulClient(null)} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      await user.selectOptions(screen.getByLabelText('Target format'), format)
      await user.click(screen.getByRole('button', { name: 'Convert image' }))
      expect(await screen.findByText(`Complete. Downloaded ${fallback}.`)).toBeVisible()
    })

    it('shows backend failures and locks a pending request against duplicates', async () => {
      const user = userEvent.setup()
      let rejectRequest: (reason: unknown) => void = () => undefined
      const client: ImageRequestClient = {
        postMultipartForBlob: vi.fn(
          () =>
            new Promise<never>((_, reject) => {
              rejectRequest = reject
            }),
        ),
      }
      render(<ConvertImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      await user.click(screen.getByRole('button', { name: 'Convert image' }))
      expect(screen.getByRole('button', { name: 'Processing…' })).toBeDisabled()
      expect(requestMock(client)).toHaveBeenCalledOnce()
      await act(async () => {
        rejectRequest(
          new ApiClientError('The uploaded image is corrupt.', {
            kind: 'http',
            status: 422,
            code: 'invalid_image',
          }),
        )
      })
      expect(await screen.findByRole('alert')).toHaveTextContent('The uploaded image is corrupt.')
    })

    it('shows a safe unavailable-backend error and remains usable', async () => {
      const user = userEvent.setup()
      const client: ImageRequestClient = {
        postMultipartForBlob: vi.fn(async () => {
          throw new ApiClientError('The DocuForge API could not be reached.', { kind: 'network' })
        }),
      }
      render(<ConvertImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      await user.click(screen.getByRole('button', { name: 'Convert image' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The DocuForge API could not be reached.',
      )
      expect(screen.getByRole('button', { name: 'Convert image' })).toBeEnabled()
    })
  })

  describe('resize', () => {
    it('rejects two blank dimensions and zero, negative, and decimal values', async () => {
      const user = userEvent.setup()
      render(<ResizeImageForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      const submit = screen.getByRole('button', { name: 'Resize image' })
      expect(screen.getByText('Enter a maximum width or height.')).toBeVisible()
      expect(screen.getByLabelText('Maximum width')).toHaveAttribute(
        'aria-describedby',
        expect.stringContaining('resize-dimensions-error'),
      )
      expect(submit).toBeDisabled()
      for (const value of ['0', '-1', '1.5']) {
        fireEvent.change(screen.getByLabelText('Maximum width'), { target: { value } })
        expect(screen.getByText('Maximum width must be a positive whole number.')).toBeVisible()
        expect(submit).toBeDisabled()
      }
    })

    it('submits width only and explicit false without an empty height', async () => {
      const user = userEvent.setup()
      const client = successfulClient(null)
      render(<ResizeImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      await user.type(screen.getByLabelText('Maximum width'), '800')
      expect(screen.getByRole('checkbox', { name: 'Allow upscaling' })).not.toBeChecked()
      await user.click(screen.getByRole('button', { name: 'Resize image' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/images/resize')
      expect(formData.get('max_width')).toBe('800')
      expect(formData.has('max_height')).toBe(false)
      expect(formData.get('allow_upscale')).toBe('false')
      expect(await screen.findByText('Complete. Downloaded resized-image.png.')).toBeVisible()
    })

    it('accepts height-only and bounding-box requests and serializes true', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<ResizeImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      await user.type(screen.getByLabelText('Maximum height'), '450')
      expect(screen.getByRole('button', { name: 'Resize image' })).toBeEnabled()
      await user.type(screen.getByLabelText('Maximum width'), '800')
      await user.click(screen.getByRole('checkbox', { name: 'Allow upscaling' }))
      await user.click(screen.getByRole('button', { name: 'Resize image' }))
      const formData = requestMock(client).mock.calls[0][1]
      expect(formData.get('max_width')).toBe('800')
      expect(formData.get('max_height')).toBe('450')
      expect(formData.get('allow_upscale')).toBe('true')
      expect(formData.get('format')).toBe('jpeg')
    })

    it('shows a safe resize backend error', async () => {
      const user = userEvent.setup()
      render(<ResizeImageForm client={failingClient('The resize dimensions are invalid.')} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      await user.type(screen.getByLabelText('Maximum height'), '100')
      await user.click(screen.getByRole('button', { name: 'Resize image' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('The resize dimensions are invalid.')
    })
  })

  describe('quality compression', () => {
    it('defaults to quality 80 and submits only quality for JPEG', async () => {
      const user = userEvent.setup()
      const client = successfulClient(null, 'image/jpeg')
      render(<CompressImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      expect(screen.getByRole('radio', { name: 'Quality' })).toBeChecked()
      expect(screen.getByLabelText('Quality', { selector: 'input[type="number"]' })).toHaveValue(80)
      await user.click(screen.getByRole('button', { name: 'Compress image' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/images/compress')
      expect(formData.get('format')).toBe('jpeg')
      expect(formData.get('quality')).toBe('80')
      expect(formData.has('max_bytes')).toBe(false)
      expect(await screen.findByText('Complete. Downloaded compressed-image.jpg.')).toBeVisible()
    })

    it.each([
      ['1', true],
      ['95', true],
      ['0', false],
      ['96', false],
      ['1.5', false],
    ])('validates quality %s', async (quality, accepted) => {
      const user = userEvent.setup()
      render(<CompressImageForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.webp', 'image/webp'))
      fireEvent.change(screen.getByLabelText('Quality', { selector: 'input[type="number"]' }), {
        target: { value: quality },
      })
      const submit = screen.getByRole('button', { name: 'Compress image' })
      if (accepted) {
        expect(submit).toBeEnabled()
      } else {
        expect(submit).toBeDisabled()
      }
    })

    it.each(['png', 'bmp', 'tiff'])('rejects %s in quality mode without changing it', async (format) => {
      const user = userEvent.setup()
      render(<CompressImageForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.jpg', 'image/jpeg'))
      await user.selectOptions(screen.getByLabelText('Target format'), format)
      expect(screen.getByLabelText('Target format')).toHaveValue(format)
      expect(screen.getByText('Quality compression is available for JPEG and WebP.')).toBeVisible()
      expect(screen.getByRole('button', { name: 'Compress image' })).toBeDisabled()
    })
  })

  describe('maximum-size compression', () => {
    it('converts KB to bytes, supports all target formats, and submits only max_bytes', async () => {
      const user = userEvent.setup()
      const client = successfulClient()
      render(<CompressImageForm client={client} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      await user.click(screen.getByRole('radio', { name: 'Maximum file size' }))
      const target = screen.getByLabelText('Maximum size (KB)')
      for (const format of ['jpeg', 'png', 'webp', 'bmp', 'tiff']) {
        await user.selectOptions(screen.getByLabelText('Target format'), format)
        fireEvent.change(target, { target: { value: '1' } })
        expect(screen.getByRole('button', { name: 'Compress image' })).toBeEnabled()
      }
      fireEvent.change(target, { target: { value: '200' } })
      await user.click(screen.getByRole('button', { name: 'Compress image' }))
      const formData = requestMock(client).mock.calls[0][1]
      expect(formData.get('max_bytes')).toBe('204800')
      expect(formData.has('quality')).toBe(false)
      expect(formData.get('format')).toBe('tiff')
    })

    it.each(['', '0', '-1', '1.5'])('rejects maximum size %s', async (target) => {
      const user = userEvent.setup()
      render(<CompressImageForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      await user.click(screen.getByRole('radio', { name: 'Maximum file size' }))
      fireEvent.change(screen.getByLabelText('Maximum size (KB)'), { target: { value: target } })
      expect(screen.getByRole('button', { name: 'Compress image' })).toBeDisabled()
    })

    it('shows an impossible-target backend error safely', async () => {
      const user = userEvent.setup()
      render(<CompressImageForm client={failingClient('The requested maximum size is not achievable.')} />)
      await user.upload(screen.getByLabelText('Image file'), image('source.png'))
      await user.click(screen.getByRole('radio', { name: 'Maximum file size' }))
      await user.type(screen.getByLabelText('Maximum size (KB)'), '1')
      await user.click(screen.getByRole('button', { name: 'Compress image' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The requested maximum size is not achievable.',
      )
    })
  })

  describe('images to PDF', () => {
    it('requires an image and exposes the exact narrower input set', () => {
      render(<ImagesToPdfForm client={successfulClient()} />)
      expect(screen.getByRole('button', { name: 'Create PDF' })).toBeDisabled()
      expect(screen.getByLabelText('Image files')).toHaveAttribute(
        'accept',
        '.jpg,.jpeg,.png,.bmp,.tif,.tiff',
      )
    })

    it('rejects WebP for image-to-PDF without submitting', async () => {
      const user = userEvent.setup({ applyAccept: false })
      const client = successfulClient()
      render(<ImagesToPdfForm client={client} />)
      await user.upload(screen.getByLabelText('Image files'), image('page.webp', 'image/webp'))
      expect(
        screen.getByText(
          'Choose JPEG, PNG, BMP, or TIFF files; WebP is not supported for this workflow.',
        ),
      ).toBeVisible()
      expect(screen.getByRole('button', { name: 'Create PDF' })).toBeDisabled()
      expect(requestMock(client)).not.toHaveBeenCalled()
    })

    it('displays and serializes selection order, including accessible reordering', async () => {
      const user = userEvent.setup()
      const client = successfulClient('attachment; filename="album.pdf"', 'application/pdf')
      render(<ImagesToPdfForm client={client} />)
      await user.upload(screen.getByLabelText('Image files'), [
        image('first.jpg', 'image/jpeg'),
        image('second.png'),
        image('third.tif', 'image/tiff'),
      ])
      await user.click(screen.getByRole('button', { name: 'Move second.png up' }))
      await user.click(screen.getByRole('button', { name: 'Move third.tif up' }))
      const names = within(screen.getByRole('list')).getAllByRole('listitem').map((item) => item.textContent)
      expect(names).toEqual([
        expect.stringContaining('second.png'),
        expect.stringContaining('third.tif'),
        expect.stringContaining('first.jpg'),
      ])
      await user.click(screen.getByRole('button', { name: 'Create PDF' }))
      const [endpoint, formData] = requestMock(client).mock.calls[0]
      expect(endpoint).toBe('/api/v1/images/to-pdf')
      expect((formData.getAll('files') as File[]).map((file) => file.name)).toEqual([
        'second.png',
        'third.tif',
        'first.jpg',
      ])
      expect(await screen.findByText('Complete. Downloaded album.pdf.')).toBeVisible()
    })

    it('supports remove and clear all', async () => {
      const user = userEvent.setup()
      render(<ImagesToPdfForm client={successfulClient()} />)
      await user.upload(screen.getByLabelText('Image files'), [image('one.png'), image('two.png')])
      await user.click(screen.getByRole('button', { name: 'Remove one.png' }))
      expect(screen.queryByText('one.png')).not.toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Clear all' }))
      expect(screen.queryByRole('list')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Create PDF' })).toBeDisabled()
    })

    it('uses images.pdf fallback and shows backend errors', async () => {
      const user = userEvent.setup()
      const fallbackClient = successfulClient(null, 'application/pdf')
      const { unmount } = render(<ImagesToPdfForm client={fallbackClient} />)
      await user.upload(screen.getByLabelText('Image files'), image('one.png'))
      await user.click(screen.getByRole('button', { name: 'Create PDF' }))
      expect(await screen.findByText('Complete. Downloaded images.pdf.')).toBeVisible()
      unmount()

      render(<ImagesToPdfForm client={failingClient('One image could not be decoded.')} />)
      await user.upload(screen.getByLabelText('Image files'), image('broken.png'))
      await user.click(screen.getByRole('button', { name: 'Create PDF' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('One image could not be decoded.')
    })
  })
})
