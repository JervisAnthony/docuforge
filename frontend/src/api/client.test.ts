import { describe, expect, it, vi } from 'vitest'
import { ApiClientError, createApiClient, joinApiUrl } from './client'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('API client', () => {
  it('gets and validates API health', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ status: 'ok', service: 'docuforge', version: '0.1.0' }),
    )
    await expect(createApiClient('', fetchMock).getHealth()).resolves.toEqual({
      status: 'ok',
      service: 'docuforge',
      version: '0.1.0',
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', {
      headers: { Accept: 'application/json' },
    })
  })

  it('gets and validates API metadata', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ name: 'DocuForge API', version: '0.1.0', status: 'available' }),
    )
    await expect(createApiClient('', fetchMock).getMetadata()).resolves.toEqual({
      name: 'DocuForge API',
      version: '0.1.0',
      status: 'available',
    })
  })

  it('normalizes configured base URLs and paths', () => {
    expect(joinApiUrl(' https://api.example.test/root/// ', '//api/v1/health')).toBe(
      'https://api.example.test/root/api/v1/health',
    )
    expect(joinApiUrl('', 'api/v1')).toBe('/api/v1')
  })

  it('wraps network failures safely', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'))
    await expect(createApiClient('', fetchMock).getHealth()).rejects.toMatchObject({
      name: 'ApiClientError',
      kind: 'network',
      status: null,
      code: null,
    })
  })

  it('uses a valid backend JSON error', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        { code: 'invalid_request', message: 'Choose a supported request.' },
        { status: 400 },
      ),
    )
    await expect(createApiClient('', fetchMock).getHealth()).rejects.toMatchObject({
      kind: 'http',
      status: 400,
      code: 'invalid_request',
      message: 'Choose a supported request.',
    })
  })

  it('rejects malformed successful JSON', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ status: 'ok', service: 'different-service', version: 1 }),
    )
    await expect(createApiClient('', fetchMock).getHealth()).rejects.toMatchObject({
      kind: 'malformed-response',
      status: 200,
    })
  })

  it('falls back safely for a malformed API error', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('not json', { status: 503 }),
    )
    const error = await createApiClient('', fetchMock).getHealth().catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiClientError)
    expect(error).toMatchObject({ kind: 'http', status: 503, code: null })
    expect((error as Error).message).toBe('The API request failed (503).')
  })

  it('posts FormData and returns a blob without setting multipart Content-Type', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('document', {
        status: 200,
        headers: { 'Content-Type': 'application/pdf' },
      }),
    )
    const formData = new FormData()
    formData.append('file', new Blob(['input']), 'input.pdf')

    await expect(
      createApiClient('https://api.example.test/', fetchMock).postMultipartForBlob(
        '/api/v1/pdf/split',
        formData,
      ),
    ).resolves.toMatchObject({ contentType: 'application/pdf' })

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.test/api/v1/pdf/split',
      expect.objectContaining({ method: 'POST', body: formData }),
    )
    const requestInit = fetchMock.mock.calls[0]?.[1]
    expect(requestInit?.headers).toEqual({ Accept: 'application/octet-stream' })
  })

  it('parses backend errors for multipart requests', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ code: 'invalid_pdf_request', message: 'A PDF is required.' }, { status: 400 }),
    )
    await expect(
      createApiClient('', fetchMock).postMultipartForBlob('/api/v1/pdf/split', new FormData()),
    ).rejects.toMatchObject({
      kind: 'http',
      status: 400,
      code: 'invalid_pdf_request',
    })
  })
})
