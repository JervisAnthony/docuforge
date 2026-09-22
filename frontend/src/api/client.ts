import type {
  ApiErrorPayload,
  ApiHealth,
  ApiMetadata,
  BatchSnapshot,
  BatchSessionHandle,
  BinaryResponse,
} from './types'

type ApiClientErrorKind = 'network' | 'http' | 'malformed-response'
type FetchImplementation = typeof fetch
export const BATCH_TOKEN_HEADER = 'X-DocuForge-Batch-Token'

export class ApiClientError extends Error {
  readonly kind: ApiClientErrorKind
  readonly status: number | null
  readonly code: string | null

  constructor(
    message: string,
    options: {
      kind: ApiClientErrorKind
      status?: number
      code?: string
      cause?: unknown
    },
  ) {
    super(message, { cause: options.cause })
    this.name = 'ApiClientError'
    this.kind = options.kind
    this.status = options.status ?? null
    this.code = options.code ?? null
  }
}

export interface ApiClient {
  getMetadata(): Promise<ApiMetadata>
  getHealth(): Promise<ApiHealth>
  postMultipartForBlob(path: string, formData: FormData): Promise<BinaryResponse>
  createBatch(path: string, formData: FormData): Promise<BatchSessionHandle>
  getBatchStatus(batchId: string, accessToken: string): Promise<BatchSnapshot>
  cancelBatch(batchId: string, accessToken: string): Promise<BatchSnapshot>
  recoverBatch(batchId: string, accessToken: string): Promise<BatchSnapshot>
  downloadBatch(batchId: string, accessToken: string): Promise<BinaryResponse>
  deleteBatch(batchId: string, accessToken: string): Promise<void>
}

export function createApiClient(
  baseUrl = '',
  fetchImplementation: FetchImplementation = fetch,
): ApiClient {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl)

  async function request(path: string, init?: RequestInit): Promise<Response> {
    try {
      return await fetchImplementation(joinApiUrl(normalizedBaseUrl, path), init)
    } catch (error: unknown) {
      throw new ApiClientError('The DocuForge API could not be reached.', {
        kind: 'network',
        cause: error,
      })
    }
  }

  async function requestJson<T>(
    path: string,
    validate: (value: unknown) => value is T,
    init?: RequestInit,
  ): Promise<T> {
    const response = await request(path, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    })
    if (!response.ok) {
      throw await createHttpError(response)
    }

    const payload = await parseJson(response)
    if (!validate(payload)) {
      throw new ApiClientError('The API returned an unexpected response.', {
        kind: 'malformed-response',
        status: response.status,
      })
    }
    return payload
  }

  return {
    getMetadata: () => requestJson('/api/v1', isApiMetadata),
    getHealth: () => requestJson('/api/v1/health', isApiHealth),
    async createBatch(path, formData) {
      const response = await request(path, {
        method: 'POST',
        body: formData,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw await createHttpError(response)
      const snapshot = await parseJson(response)
      const accessToken = response.headers.get(BATCH_TOKEN_HEADER)
      if (!isBatchSnapshot(snapshot) || !accessToken?.trim()) {
        throw new ApiClientError('The API returned an unexpected response.', {
          kind: 'malformed-response',
          status: response.status,
        })
      }
      return { snapshot, accessToken }
    },
    getBatchStatus: (batchId, accessToken) => requestJson(
      batchPath(batchId), isBatchSnapshot, { headers: batchAccessHeaders(accessToken) },
    ),
    cancelBatch: (batchId, accessToken) =>
      requestJson(`${batchPath(batchId)}/cancel`, isBatchSnapshot, {
        method: 'POST', headers: batchAccessHeaders(accessToken),
      }),
    recoverBatch: (batchId, accessToken) =>
      requestJson(`${batchPath(batchId)}/recover`, isBatchSnapshot, {
        method: 'POST', headers: batchAccessHeaders(accessToken),
      }),
    async downloadBatch(batchId, accessToken) {
      const response = await request(`${batchPath(batchId)}/download`, {
        headers: { Accept: 'application/zip', ...batchAccessHeaders(accessToken) },
      })
      if (!response.ok) throw await createHttpError(response)
      return {
        blob: await response.blob(),
        contentType: response.headers.get('content-type'),
        contentDisposition: response.headers.get('content-disposition'),
      }
    },
    async deleteBatch(batchId, accessToken) {
      const response = await request(batchPath(batchId), {
        method: 'DELETE',
        headers: batchAccessHeaders(accessToken),
      })
      if (!response.ok) throw await createHttpError(response)
    },
    async postMultipartForBlob(path, formData) {
      const response = await request(path, {
        method: 'POST',
        body: formData,
        headers: { Accept: 'application/octet-stream' },
      })
      if (!response.ok) {
        throw await createHttpError(response)
      }
      return {
        blob: await response.blob(),
        contentType: response.headers.get('content-type'),
        contentDisposition: response.headers.get('content-disposition'),
      }
    },
  }
}

export function joinApiUrl(baseUrl: string, path: string): string {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl)
  const normalizedPath = `/${path.trim().replace(/^\/+/, '')}`
  return `${normalizedBaseUrl}${normalizedPath}`
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '')
}

async function createHttpError(response: Response): Promise<ApiClientError> {
  const payload = await parseJson(response)
  if (isApiErrorPayload(payload)) {
    return new ApiClientError(payload.message, {
      kind: 'http',
      status: response.status,
      code: payload.code,
    })
  }
  return new ApiClientError(`The API request failed (${response.status}).`, {
    kind: 'http',
    status: response.status,
  })
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isApiMetadata(value: unknown): value is ApiMetadata {
  return (
    isRecord(value) &&
    typeof value.name === 'string' &&
    typeof value.version === 'string' &&
    value.status === 'available'
  )
}

function isApiHealth(value: unknown): value is ApiHealth {
  return (
    isRecord(value) &&
    value.status === 'ok' &&
    value.service === 'docuforge' &&
    typeof value.version === 'string'
  )
}

function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  return (
    isRecord(value) &&
    typeof value.code === 'string' &&
    typeof value.message === 'string'
  )
}

function batchPath(batchId: string): string {
  return `/api/v1/batches/${encodeURIComponent(batchId)}`
}

function batchAccessHeaders(accessToken: string): Record<string, string> {
  return { [BATCH_TOKEN_HEADER]: accessToken }
}

const ITEM_STATUSES = new Set(['pending', 'running', 'completed', 'failed', 'cancelled'])
const BATCH_STATUSES = new Set(['pending', 'running', 'completed', 'failed', 'partial', 'cancelled'])
const BATCH_PHASES = new Set(['queued', 'processing', 'cancelling', 'packaging', 'ready', 'error'])

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isFailure(value: unknown): value is { code: string; message: string } {
  return isRecord(value) && typeof value.code === 'string' && typeof value.message === 'string'
}

function isNullableFailure(value: unknown): boolean {
  return value === null || isFailure(value)
}

function isBatchItem(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    isNonNegativeInteger(value.position) &&
    typeof value.descriptor === 'string' &&
    typeof value.status === 'string' &&
    ITEM_STATUSES.has(value.status) &&
    (value.result_descriptor === null || typeof value.result_descriptor === 'string') &&
    isNullableFailure(value.failure)
  )
}

function isBatchSummary(value: unknown): boolean {
  return (
    isRecord(value) &&
    ['total', 'pending', 'running', 'completed', 'failed', 'cancelled', 'processed', 'remaining'].every(
      (key) => isNonNegativeInteger(value[key]),
    )
  )
}

function isBatchSnapshot(value: unknown): value is BatchSnapshot {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.operation === 'string' &&
    isNonNegativeInteger(value.attempt) && value.attempt > 0 &&
    typeof value.phase === 'string' && BATCH_PHASES.has(value.phase) &&
    typeof value.status === 'string' && BATCH_STATUSES.has(value.status) &&
    isNonNegativeInteger(value.progress_percent) && value.progress_percent <= 100 &&
    typeof value.cancellation_requested === 'boolean' &&
    isBatchSummary(value.summary) &&
    Array.isArray(value.items) && value.items.every(isBatchItem) &&
    isNullableFailure(value.session_error) &&
    typeof value.can_cancel === 'boolean' &&
    typeof value.can_recover === 'boolean' &&
    typeof value.can_download === 'boolean'
  )
}

export const apiClient = createApiClient(import.meta.env.VITE_API_BASE_URL)
