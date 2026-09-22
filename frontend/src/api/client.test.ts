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
  const batch = {
    id: 'batch-1', operation: 'image.convert', attempt: 1, phase: 'ready', status: 'completed', progress_percent: 100,
    cancellation_requested: false,
    summary: { total: 1, pending: 0, running: 0, completed: 1, failed: 0, cancelled: 0, processed: 1, remaining: 0 },
    items: [{ id: 'item-1', position: 0, descriptor: 'photo.png', status: 'completed', result_descriptor: '0001-photo.jpg', failure: null }],
    session_error: null, can_cancel: false, can_recover: false, can_download: true,
  }
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
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'attachment; filename="result.pdf"',
        },
      }),
    )
    const formData = new FormData()
    formData.append('file', new Blob(['input']), 'input.pdf')

    await expect(
      createApiClient('https://api.example.test/', fetchMock).postMultipartForBlob(
        '/api/v1/pdf/split',
        formData,
      ),
    ).resolves.toMatchObject({
      contentType: 'application/pdf',
      contentDisposition: 'attachment; filename="result.pdf"',
    })

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

  it('creates, polls, controls, and downloads batches through explicit methods', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(batch, {
        status: 202,
        headers: { 'X-DocuForge-Batch-Token': 'private-token' },
      }))
      .mockResolvedValueOnce(jsonResponse(batch))
      .mockResolvedValueOnce(jsonResponse(batch, { status: 202 }))
      .mockResolvedValueOnce(jsonResponse(batch, { status: 202 }))
      .mockResolvedValueOnce(new Response('zip', { headers: { 'Content-Type': 'application/zip' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const client = createApiClient('', fetchMock)
    await expect(client.createBatch('/api/v1/batches/images/convert', new FormData())).resolves.toEqual({
      snapshot: batch,
      accessToken: 'private-token',
    })
    await client.getBatchStatus('batch/unsafe', 'private-token')
    await client.cancelBatch('batch-1', 'private-token')
    await client.recoverBatch('batch-1', 'private-token')
    await expect(client.downloadBatch('batch-1', 'private-token')).resolves.toMatchObject({ contentType: 'application/zip' })
    await expect(client.deleteBatch('batch-1', 'private-token')).resolves.toBeUndefined()
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/batches/images/convert',
      '/api/v1/batches/batch%2Funsafe',
      '/api/v1/batches/batch-1/cancel',
      '/api/v1/batches/batch-1/recover',
      '/api/v1/batches/batch-1/download',
      '/api/v1/batches/batch-1',
    ])
    for (const [, init] of fetchMock.mock.calls.slice(1)) {
      expect(init?.headers).toMatchObject({ 'X-DocuForge-Batch-Token': 'private-token' })
    }
    expect(fetchMock.mock.calls.map(([url]) => String(url)).join()).not.toContain('private-token')
    const creationBody = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect(Array.from(creationBody.values())).not.toContain('private-token')
    expect(fetchMock.mock.calls.at(-1)?.[1]).toMatchObject({ method: 'DELETE' })
    expect(fetchMock.mock.calls.at(-1)?.[1]).not.toHaveProperty('body')
  })

  it.each([404, 409, 503])('uses API errors for DELETE %s', async (status) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ code: 'batch_deletion_failed', message: 'Retry the deletion.' }, { status }),
    )
    await expect(createApiClient('', fetchMock).deleteBatch('batch-1', 'private-token')).rejects.toMatchObject({
      kind: 'http', status, code: 'batch_deletion_failed',
    })
  })

  it('rejects a creation response without a nonblank capability header', async () => {
    for (const headers of [undefined, { 'X-DocuForge-Batch-Token': '   ' }]) {
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(batch, { status: 202, headers }),
      )
      await expect(
        createApiClient('', fetchMock).createBatch('/api/v1/batches/images/convert', new FormData()),
      ).rejects.toMatchObject({ kind: 'malformed-response', status: 202 })
    }
  })

  it('rejects malformed batch status JSON', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...batch, progress_percent: 101 }))
    await expect(createApiClient('', fetchMock).getBatchStatus('batch-1', 'private-token')).rejects.toMatchObject({ kind: 'malformed-response' })
  })
})
